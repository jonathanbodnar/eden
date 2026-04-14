"""ChatAnswerBuilder: receives a user query, retrieves relevant evidence using
PostgreSQL full-text search across source records, extracted text, and segments,
calls DeepSeek (or Anthropic fallback) for a grounded answer, creates
answer_packets with linked sources/context."""

from __future__ import annotations

import json
import logging
import re
import uuid

import httpx
from sqlalchemy import Integer, func, or_, select, text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from src.canon.config import settings
from src.canon.models.answer_packet import AnswerPacket, AnswerPacketContext, AnswerPacketSource
from src.canon.models.chapter_context_set import ChapterContextSet
from src.canon.models.chapter_source_set import ChapterSourceSet
from src.canon.models.chat_session import ChatMessage, ChatSession
from src.canon.models.enums import AnswerMode, ChatRole
from src.canon.models.system_a import SAContextualStatement, SASegment, SASourceRecord, SASourceVersion

logger = logging.getLogger(__name__)

CHAT_SYSTEM_PROMPT = """You are a scholarly research assistant for an ancient history and mythology research platform called Edinworld.
The platform contains primary source records, text segments, and contextual analysis from museums, text corpora, and historical archives worldwide.

You answer questions using ONLY the provided source evidence: source records (with titles, culture, category, excerpts) and text segments (actual content from these sources).

Rules:
- Base your answer ONLY on the provided evidence. Do NOT add information from your own knowledge.
- When referencing a source, mention it by title and culture.
- Quote relevant text segments when they directly support a point.
- If multiple sources disagree, present both perspectives.
- If the evidence is only partially relevant, answer what you can and note what's missing.
- If NO evidence is relevant, say so and suggest the user try different search terms.
- Be conversational, concise, and scholarly.
- Keep answers to 2-4 paragraphs maximum."""

CHAT_SYSTEM_PROMPT_JSON = CHAT_SYSTEM_PROMPT + """

You MUST respond with valid JSON in this exact format (no markdown, no extra text):
{"answer": "your answer text", "confidence": 0.8, "answer_mode": "source", "referenced_source_indices": [0, 1], "referenced_context_indices": [0]}

answer_mode must be one of: source, context, synthesis, unsupported
- source = directly backed by primary sources
- context = based on scholarly interpretation
- synthesis = combines multiple sources
- unsupported = insufficient evidence
confidence is 0.0 to 1.0
referenced_source_indices and referenced_context_indices are arrays of integers indexing into the provided sources/texts lists."""

ANSWER_TOOL = {
    "name": "provide_answer",
    "description": "Provide a grounded answer based on the evidence",
    "input_schema": {
        "type": "object",
        "properties": {
            "answer": {"type": "string", "description": "The scholarly answer text"},
            "confidence": {"type": "number", "description": "0.0 to 1.0"},
            "answer_mode": {
                "type": "string",
                "enum": ["source", "context", "synthesis", "unsupported"],
            },
            "referenced_source_indices": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Indices of sources referenced in the answer",
            },
            "referenced_context_indices": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Indices of text segments referenced in the answer",
            },
        },
        "required": ["answer", "confidence", "answer_mode"],
    },
}

STOP_WORDS = {
    "the", "a", "an", "is", "was", "were", "are", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "of", "in", "to", "for",
    "with", "on", "at", "from", "by", "about", "as", "into", "through",
    "during", "before", "after", "above", "below", "between", "and", "but",
    "or", "not", "no", "so", "if", "then", "than", "too", "very", "just",
    "that", "this", "these", "those", "it", "its", "what", "which", "who",
    "whom", "how", "when", "where", "why", "all", "each", "every", "both",
    "few", "more", "most", "other", "some", "such", "any", "only", "own",
    "same", "tell", "me", "i", "my", "you", "your", "we", "our", "they",
    "their", "there", "here", "up", "out", "many", "much", "according",
}

# Categories that contain actual readable text content
TEXT_CATEGORIES = ("text_corpus", "public_domain_library")


SYNONYM_MAP = {
    "humans": ["mankind", "man", "humanity", "people", "mortals"],
    "made": ["created", "fashioned", "formed", "creation"],
    "god": ["deity", "divine", "gods"],
    "gods": ["deities", "divine", "pantheon"],
    "sumerian": ["sumer", "mesopotamian", "mesopotamia"],
    "babylonian": ["babylon", "akkadian", "mesopotamian"],
    "egyptian": ["egypt", "pharaoh"],
    "creation": ["created", "fashioned", "formed", "origin", "genesis"],
    "flood": ["deluge"],
    "tablets": ["tablet", "inscription", "cuneiform"],
}


def _extract_keywords(query: str) -> list[str]:
    words = re.findall(r"[a-zA-ZÀ-ÿ'ʼ]{2,}", query.lower())
    keywords = [w for w in words if w not in STOP_WORDS]
    seen: list[str] = []
    for w in keywords:
        if w not in seen:
            seen.append(w)
    return seen[:12]


def _expand_keywords(keywords: list[str]) -> list[str]:
    """Expand keywords with synonyms for better recall."""
    expanded = list(keywords)
    for kw in keywords:
        if kw in SYNONYM_MAP:
            for syn in SYNONYM_MAP[kw]:
                if syn not in expanded:
                    expanded.append(syn)
    return expanded[:20]


def _build_tsquery_and(keywords: list[str]) -> str:
    """AND query — all keywords must match."""
    if not keywords:
        return ""
    terms = [f"{kw}:*" for kw in keywords]
    return " & ".join(terms)


def _build_tsquery_or(keywords: list[str]) -> str:
    """OR query — any keyword matches."""
    if not keywords:
        return ""
    terms = [f"{kw}:*" for kw in keywords]
    return " | ".join(terms)


def _extract_relevant_passage(text: str, keywords: list[str], max_len: int = 1200) -> str:
    """Extract the most relevant passage from text around keyword matches.
    Uses a sliding window to find the densest concentration of keywords."""
    if not text or not keywords:
        return (text or "")[:max_len]

    if len(text) <= max_len:
        return text

    text_lower = text.lower()
    best_pos = -1
    best_score = 0
    step = max(50, max_len // 10)

    for i in range(0, max(1, len(text_lower) - max_len), step):
        window = text_lower[i:i + max_len]
        # Score: count of distinct keywords present + total occurrences
        distinct = sum(1 for kw in keywords if kw in window)
        total = sum(window.count(kw) for kw in keywords)
        score = distinct * 10 + total
        if score > best_score:
            best_score = score
            best_pos = i

    if best_pos < 0 or best_score == 0:
        return text[:max_len]

    start = max(0, best_pos)
    end = min(len(text), start + max_len)

    # Align to sentence boundaries
    if start > 0:
        period = text.rfind('. ', max(0, start - 80), start + 80)
        if period > 0:
            start = period + 2
    period_end = text.find('. ', max(end - 80, start), end + 80)
    if period_end > 0:
        end = period_end + 1

    return text[start:end].strip()


class ChatAnswerBuilder:
    def __init__(self):
        self._anthropic_client = None

    @property
    def anthropic_client(self):
        if self._anthropic_client is None:
            import anthropic
            self._anthropic_client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        return self._anthropic_client

    @property
    def _use_deepseek(self) -> bool:
        return bool(settings.deepseek_api_key)

    async def answer_query(
        self,
        session: AsyncSession,
        query: str,
        chapter_id: uuid.UUID | None = None,
        epoch_id: uuid.UUID | None = None,
        session_id: uuid.UUID | None = None,
    ) -> dict:
        # Retrieve evidence FIRST (before any ORM inserts) to avoid
        # polluting the session if raw SQL queries fail
        sources, contexts = await self._retrieve_evidence(
            session, query, chapter_id=chapter_id, epoch_id=epoch_id
        )

        if session_id:
            chat_session = await session.get(ChatSession, session_id)
        else:
            chat_session = ChatSession(id=uuid.uuid4(), chapter_id=chapter_id)
            session.add(chat_session)
            await session.flush()

        user_msg = ChatMessage(
            id=uuid.uuid4(),
            session_id=chat_session.id,
            role=ChatRole.USER.value,
            content=query,
        )
        session.add(user_msg)

        if not sources and not contexts:
            answer_packet = await self._create_unsupported_packet(session, query, chapter_id)
        else:
            answer_packet = await self._call_llm_and_create_packet(
                session, query, chapter_id, sources, contexts
            )

        assistant_msg = ChatMessage(
            id=uuid.uuid4(),
            session_id=chat_session.id,
            role=ChatRole.ASSISTANT.value,
            content=answer_packet.answer_summary,
            answer_packet_id=answer_packet.id,
        )
        session.add(assistant_msg)
        await session.flush()

        return {
            "session_id": str(chat_session.id),
            "answer_packet_id": str(answer_packet.id),
            "answer": answer_packet.answer_summary,
            "answer_mode": answer_packet.answer_mode,
            "confidence": answer_packet.confidence,
            "sources": [
                {
                    "id": str(s.id),
                    "source_record_id": str(s.source_record_id),
                    "excerpt": s.excerpt,
                    "support_type": s.support_type,
                    "weight": s.weight,
                }
                for s in (await self._get_packet_sources(session, answer_packet.id))
            ],
            "contexts": [
                {
                    "id": str(c.id),
                    "contextual_statement_id": str(c.contextual_statement_id),
                    "summary": c.summary,
                    "weight": c.weight,
                }
                for c in (await self._get_packet_contexts(session, answer_packet.id))
            ],
        }

    async def _retrieve_evidence(
        self,
        session: AsyncSession,
        query: str,
        chapter_id: uuid.UUID | None = None,
        epoch_id: uuid.UUID | None = None,
    ) -> tuple[list[dict], list[dict]]:
        """Multi-strategy evidence retrieval with AND-first, OR-fallback logic."""
        keywords = _extract_keywords(query)
        if not keywords:
            keywords = query.lower().split()[:5]

        expanded = _expand_keywords(keywords)

        # Build a few targeted AND queries:
        # 1) Original keywords AND (most precise)
        # 2) Synonym-expanded version (broader match for same concept)
        and_queries: list[str] = []
        if len(keywords) <= 4:
            and_queries.append(_build_tsquery_and(keywords))
        else:
            # Too many keywords for AND — take top 3 by specificity
            and_queries.append(_build_tsquery_and(keywords[:3]))

        # Build an expanded AND query substituting synonyms for key terms
        concept_kw = []
        for kw in keywords[:4]:
            if kw in SYNONYM_MAP:
                concept_kw.append(SYNONYM_MAP[kw][0])
            else:
                concept_kw.append(kw)
        concept_q = _build_tsquery_and(concept_kw[:3])
        if concept_q and concept_q not in and_queries:
            and_queries.append(concept_q)

        tsq_or = _build_tsquery_or(expanded)

        # Each strategy is wrapped so a failure in one doesn't kill the others
        text_sources: list[dict] = []
        title_sources: list[dict] = []
        contexts: list[dict] = []

        all_tsq_and = [q for q in and_queries if q][:3]

        try:
            text_sources = await self._fts_text_content(session, all_tsq_and, tsq_or, expanded)
        except Exception:
            logger.exception("Text content search failed")
            await session.rollback()

        try:
            title_sources = await self._fts_source_records(session, all_tsq_and, tsq_or, expanded)
        except Exception:
            logger.exception("Title search failed")
            await session.rollback()

        try:
            contexts = await self._fts_segments(session, all_tsq_and, tsq_or, expanded)
        except Exception:
            logger.exception("Segment search failed")
            await session.rollback()

        # Merge and dedup source results, keeping highest weight
        seen: dict[uuid.UUID, dict] = {}
        # Text content matches get priority
        for s in text_sources:
            sid = s["source_record_id"]
            if sid not in seen or s["weight"] > seen[sid]["weight"]:
                seen[sid] = s
        for s in title_sources:
            sid = s["source_record_id"]
            if sid not in seen or s["weight"] > seen[sid]["weight"]:
                seen[sid] = s

        sources = sorted(seen.values(), key=lambda x: x["weight"], reverse=True)[:15]

        return sources, contexts

    async def _fts_text_content(
        self, session: AsyncSession, tsq_ands: list[str], tsq_or: str, keywords: list[str]
    ) -> list[dict]:
        """Search source_versions.text_extracted — where the actual readable content lives.
        Prioritizes text_corpus and library sources over museum catalog entries."""
        results = []
        existing_ids: set = set()

        # Try each AND query for precise matches
        for tsq_and in tsq_ands:
            if not tsq_and:
                continue
            sql = sa_text("""
                SELECT sr.id, sr.canonical_title, sr.culture, sr.source_category,
                       ts_rank(sv.tsv, to_tsquery('english', :tsq)) * 
                         CASE WHEN sr.source_category::text IN ('text_corpus', 'public_domain_library') 
                              THEN 3.0 ELSE 1.0 END as rank,
                       sv.text_extracted
                FROM source_versions sv
                JOIN source_records sr ON sr.id = sv.source_record_id
                WHERE sv.tsv @@ to_tsquery('english', :tsq)
                  AND sv.text_extracted IS NOT NULL
                  AND length(sv.text_extracted) > 200
                ORDER BY rank DESC
                LIMIT 15
            """)
            try:
                rows = (await session.execute(sql, {"tsq": tsq_and})).fetchall()
                for row in rows:
                    if row.id not in existing_ids:
                        excerpt = _extract_relevant_passage(row.text_extracted, keywords)
                        results.append({
                            "source_record_id": row.id,
                            "title": row.canonical_title,
                            "culture": row.culture,
                            "excerpt": excerpt,
                            "source_type": row.source_category,
                            "weight": float(row.rank or 1) * 2.0,
                        })
                        existing_ids.add(row.id)
            except Exception:
                logger.exception("FTS text_content AND query failed for: %s", tsq_and)

        if len(results) < 10 and tsq_or:
            existing_ids = {r["source_record_id"] for r in results}
            sql = sa_text("""
                SELECT sr.id, sr.canonical_title, sr.culture, sr.source_category,
                       ts_rank(sv.tsv, to_tsquery('english', :tsq)) *
                         CASE WHEN sr.source_category::text IN ('text_corpus', 'public_domain_library')
                              THEN 3.0 ELSE 1.0 END as rank,
                       sv.text_extracted
                FROM source_versions sv
                JOIN source_records sr ON sr.id = sv.source_record_id
                WHERE sv.tsv @@ to_tsquery('english', :tsq)
                  AND sv.text_extracted IS NOT NULL
                  AND length(sv.text_extracted) > 200
                ORDER BY rank DESC
                LIMIT 20
            """)
            try:
                rows = (await session.execute(sql, {"tsq": tsq_or})).fetchall()
                for row in rows:
                    if row.id not in existing_ids:
                        excerpt = _extract_relevant_passage(row.text_extracted, keywords)
                        results.append({
                            "source_record_id": row.id,
                            "title": row.canonical_title,
                            "culture": row.culture,
                            "excerpt": excerpt,
                            "source_type": row.source_category,
                            "weight": float(row.rank or 1),
                        })
                        existing_ids.add(row.id)
            except Exception:
                logger.exception("FTS text_content OR query failed")

        return results

    async def _fts_source_records(
        self, session: AsyncSession, tsq_ands: list[str], tsq_or: str, keywords: list[str]
    ) -> list[dict]:
        """Search source_records by title/culture metadata."""
        results = []
        tsq = (tsq_ands[0] if tsq_ands else None) or tsq_or
        if not tsq:
            return []

        sql = sa_text("""
            SELECT sr.id, sr.canonical_title, sr.culture, sr.source_category,
                   ts_rank(sr.tsv, to_tsquery('english', :tsq)) *
                     CASE WHEN sr.source_category::text IN ('text_corpus', 'public_domain_library')
                          THEN 3.0 ELSE 1.0 END as rank,
                   LEFT(sv.text_extracted, 800) as excerpt
            FROM source_records sr
            LEFT JOIN LATERAL (
                SELECT text_extracted FROM source_versions
                WHERE source_record_id = sr.id AND text_extracted IS NOT NULL
                ORDER BY length(text_extracted) DESC
                LIMIT 1
            ) sv ON true
            WHERE sr.tsv @@ to_tsquery('english', :tsq)
            ORDER BY rank DESC
            LIMIT 15
        """)
        try:
            rows = (await session.execute(sql, {"tsq": tsq})).fetchall()
            for row in rows:
                excerpt = row.excerpt or ""
                if excerpt and keywords:
                    excerpt = _extract_relevant_passage(excerpt, keywords, 500)
                results.append({
                    "source_record_id": row.id,
                    "title": row.canonical_title,
                    "culture": row.culture,
                    "excerpt": excerpt,
                    "source_type": row.source_category,
                    "weight": float(row.rank or 1),
                })
        except Exception:
            logger.exception("FTS source_records query failed, falling back to ILIKE")
            return await self._ilike_source_records(session, keywords)

        return results

    async def _ilike_source_records(
        self, session: AsyncSession, keywords: list[str]
    ) -> list[dict]:
        if not keywords:
            return []

        any_conditions = []
        for kw in keywords:
            pattern = f"%{kw}%"
            any_conditions.append(SASourceRecord.canonical_title.ilike(pattern))
            any_conditions.append(SASourceRecord.culture.ilike(pattern))

        all_match = SASourceRecord.canonical_title.ilike(f"%{keywords[0]}%")
        for kw in keywords[1:]:
            all_match = all_match & SASourceRecord.canonical_title.ilike(f"%{kw}%")

        q = (
            select(SASourceRecord)
            .where(or_(all_match, *any_conditions))
            .limit(20)
        )
        rows = (await session.execute(q)).scalars().all()

        sources = []
        seen: set[uuid.UUID] = set()
        for rec in rows:
            if rec.id in seen:
                continue
            seen.add(rec.id)
            excerpt = ""
            ver_q = (
                select(SASourceVersion)
                .where(SASourceVersion.source_record_id == rec.id)
                .where(SASourceVersion.text_extracted.isnot(None))
                .limit(1)
            )
            ver = (await session.execute(ver_q)).scalar_one_or_none()
            if ver and ver.text_extracted:
                excerpt = _extract_relevant_passage(ver.text_extracted, keywords)

            title_lower = (rec.canonical_title or "").lower()
            weight = sum(1 for kw in keywords if kw in title_lower)
            if rec.source_category in TEXT_CATEGORIES:
                weight *= 2
            sources.append({
                "source_record_id": rec.id,
                "title": rec.canonical_title,
                "culture": rec.culture,
                "excerpt": excerpt,
                "source_type": rec.source_category,
                "weight": float(max(weight, 1)),
            })

        sources.sort(key=lambda x: x["weight"], reverse=True)
        return sources[:15]

    async def _fts_segments(
        self, session: AsyncSession, tsq_ands: list[str], tsq_or: str, keywords: list[str]
    ) -> list[dict]:
        tsq = (tsq_ands[0] if tsq_ands else None) or tsq_or
        if not tsq:
            return []

        sql = sa_text("""
            SELECT s.id, LEFT(s.normalized_text, 800) as excerpt,
                   ts_rank(s.tsv, to_tsquery('english', :tsq)) as rank
            FROM segments s
            WHERE s.tsv @@ to_tsquery('english', :tsq)
            ORDER BY rank DESC
            LIMIT 15
        """)
        try:
            rows = (await session.execute(sql, {"tsq": tsq})).fetchall()
        except Exception:
            logger.exception("FTS segments query failed, falling back to ILIKE")
            return await self._ilike_segments(session, keywords)

        return [
            {
                "contextual_statement_id": row.id,
                "summary": row.excerpt or "",
                "weight": float(row.rank or 1),
            }
            for row in rows
        ]

    async def _ilike_segments(
        self, session: AsyncSession, keywords: list[str]
    ) -> list[dict]:
        if not keywords:
            return []

        any_conditions = []
        for kw in keywords:
            any_conditions.append(SASourceVersion.text_extracted.ilike(f"%{kw}%"))

        q = (
            select(SASourceVersion)
            .where(or_(*any_conditions))
            .where(SASourceVersion.text_extracted.isnot(None))
            .where(SASourceVersion.text_extracted != "")
            .limit(15)
        )
        rows = (await session.execute(q)).scalars().all()

        return [
            {
                "contextual_statement_id": sv.id,
                "summary": _extract_relevant_passage(sv.text_extracted or "", keywords, 600),
                "weight": 1.0,
            }
            for sv in rows
        ]

    def _build_evidence_prompt(self, query: str, sources: list[dict], contexts: list[dict]) -> str:
        parts = [f"User question: {query}\n"]

        if sources:
            parts.append("== Source Records ==")
            for i, s in enumerate(sources):
                culture = f" ({s['culture']})" if s.get("culture") else ""
                parts.append(f"[Source {i}] {s['title']}{culture}")
                if s.get("excerpt"):
                    parts.append(f"  Content: {s['excerpt'][:800]}")
                parts.append(f"  Category: {s.get('source_type', 'unknown')}")
                parts.append("")

        if contexts:
            parts.append("== Text Segments / Evidence ==")
            for i, c in enumerate(contexts):
                parts.append(f"[Text {i}] {c['summary']}")
                parts.append("")

        if not sources and not contexts:
            parts.append("(No relevant evidence found in the database for this query.)")

        return "\n".join(parts)

    async def _call_deepseek(self, prompt: str) -> dict:
        url = f"{settings.deepseek_base_url.rstrip('/')}/chat/completions"
        payload = {
            "model": settings.deepseek_model,
            "messages": [
                {"role": "system", "content": CHAT_SYSTEM_PROMPT_JSON},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.3,
            "max_tokens": 2048,
        }
        headers = {
            "Authorization": f"Bearer {settings.deepseek_api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        raw = data["choices"][0]["message"]["content"]
        raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
        json_match = re.search(r"\{.*\}", raw, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
        raise ValueError(f"No JSON found in DeepSeek response: {raw[:300]}")

    async def _call_anthropic(self, prompt: str) -> dict:
        try:
            response = await self.anthropic_client.messages.create(
                model=settings.anthropic_model,
                max_tokens=4096,
                system=CHAT_SYSTEM_PROMPT,
                tools=[ANSWER_TOOL],
                tool_choice={"type": "tool", "name": "provide_answer"},
                messages=[{"role": "user", "content": prompt}],
            )
            for block in response.content:
                if block.type == "tool_use" and block.name == "provide_answer":
                    return block.input
        except Exception:
            logger.exception("Anthropic chat answer failed")
        return {
            "answer": "I encountered an error processing your question. Please try again.",
            "confidence": 0.0,
            "answer_mode": "unsupported",
        }

    async def _call_llm_and_create_packet(
        self,
        session: AsyncSession,
        query: str,
        chapter_id: uuid.UUID | None,
        sources: list[dict],
        contexts: list[dict],
    ) -> AnswerPacket:
        prompt = self._build_evidence_prompt(query, sources, contexts)

        answer_data = None

        if self._use_deepseek:
            try:
                answer_data = await self._call_deepseek(prompt)
                logger.info("DeepSeek answered query: %s", query[:80])
            except Exception:
                logger.exception("DeepSeek chat failed, trying fallback")
                answer_data = None

        if answer_data is None and settings.anthropic_api_key:
            try:
                answer_data = await self._call_anthropic(prompt)
                logger.info("Anthropic fallback answered query: %s", query[:80])
            except Exception:
                logger.exception("Anthropic fallback also failed")
                answer_data = None

        if answer_data is None:
            answer_data = {
                "answer": "I encountered an error processing your question. Please try again.",
                "confidence": 0.0,
                "answer_mode": "unsupported",
            }

        packet = AnswerPacket(
            id=uuid.uuid4(),
            query=query,
            chapter_id=chapter_id,
            answer_mode=answer_data.get("answer_mode", "unsupported"),
            answer_summary=answer_data.get("answer", ""),
            confidence=answer_data.get("confidence", 0.0),
        )
        session.add(packet)
        await session.flush()

        ref_src = answer_data.get("referenced_source_indices", list(range(min(5, len(sources)))))
        for idx in ref_src:
            if 0 <= idx < len(sources):
                s = sources[idx]
                ps = AnswerPacketSource(
                    id=uuid.uuid4(),
                    answer_packet_id=packet.id,
                    source_record_id=s["source_record_id"],
                    excerpt=s.get("excerpt"),
                    support_type=s.get("source_type"),
                    weight=s.get("weight", 1.0),
                )
                session.add(ps)

        ref_ctx = answer_data.get("referenced_context_indices", list(range(min(5, len(contexts)))))
        for idx in ref_ctx:
            if 0 <= idx < len(contexts):
                c = contexts[idx]
                pc = AnswerPacketContext(
                    id=uuid.uuid4(),
                    answer_packet_id=packet.id,
                    contextual_statement_id=c["contextual_statement_id"],
                    summary=c.get("summary"),
                    weight=c.get("weight", 1.0),
                )
                session.add(pc)

        return packet

    async def _create_unsupported_packet(
        self, session: AsyncSession, query: str, chapter_id: uuid.UUID | None
    ) -> AnswerPacket:
        packet = AnswerPacket(
            id=uuid.uuid4(),
            query=query,
            chapter_id=chapter_id,
            answer_mode=AnswerMode.UNSUPPORTED.value,
            answer_summary="No relevant evidence was found for this query. Try rephrasing with specific names, places, cultures, or time periods.",
            confidence=0.0,
        )
        session.add(packet)
        await session.flush()
        return packet

    async def _get_packet_sources(self, session: AsyncSession, packet_id: uuid.UUID) -> list[AnswerPacketSource]:
        q = select(AnswerPacketSource).where(AnswerPacketSource.answer_packet_id == packet_id)
        return list((await session.execute(q)).scalars().all())

    async def _get_packet_contexts(self, session: AsyncSession, packet_id: uuid.UUID) -> list[AnswerPacketContext]:
        q = select(AnswerPacketContext).where(AnswerPacketContext.answer_packet_id == packet_id)
        return list((await session.execute(q)).scalars().all())
