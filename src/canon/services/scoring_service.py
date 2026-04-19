"""Scoring-service: calculates confidence scores for canonical entities.

Enhanced 6-factor formula implementing the 16 Laws of Synthesis:
  final = (age * 0.25) + (corroboration * 0.20) + (independence * 0.20)
        + (citation * 0.15) + (pattern * 0.10) - (ambiguity * 0.10)

Laws implemented:
  Law 4  (Age-Weighted Priority)       -> age_score
  Law 5  (Cross-Cultural Convergence)  -> independence_score (distinct cultures)
  Law 6  (Distribution Independence)   -> corroboration normalised per culture
  Law 7  (Pattern Dominance)           -> pattern_score (motif recurrence)
  Law 4+ (Bidirectional Citation)      -> citation_score (later sources referencing older events)

Thresholds:
  high (>0.7)   -> core_canon
  medium (0.4-0.7) -> canon_with_caution
  low (<0.4)    -> branch
"""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from datetime import datetime

from sqlalchemy import select, func, distinct, case, and_
from sqlalchemy.ext.asyncio import AsyncSession

from src.canon.models.canonical_actor import CanonicalActor
from src.canon.models.canonical_event import CanonicalEvent
from src.canon.models.canonical_place import CanonicalPlace
from src.canon.models.canon_score import CanonScore
from src.canon.models.canon_support_link import CanonSupportLink
from src.canon.models.enums import CanonicalType, SupportType
from src.canon.models.motif import Motif, MotifAssignment
from src.canon.models.system_a import SATrustedSource, SARawObject, SASourceRecord, SASourceDate

logger = logging.getLogger(__name__)

AGE_WEIGHT = 0.25
CORROBORATION_WEIGHT = 0.20
INDEPENDENCE_WEIGHT = 0.20
CITATION_WEIGHT = 0.15
PATTERN_WEIGHT = 0.10
AMBIGUITY_WEIGHT = 0.10


class ScoringService:

    async def _count_support_links(
        self, session: AsyncSession, canonical_type: CanonicalType, canonical_id: uuid.UUID
    ) -> dict:
        """Count support links by type for a canonical entity."""
        q = select(
            CanonSupportLink.support_type,
            func.count(CanonSupportLink.id),
            func.sum(CanonSupportLink.weight),
        ).where(
            CanonSupportLink.canonical_type == canonical_type,
            CanonSupportLink.canonical_id == canonical_id,
        ).group_by(CanonSupportLink.support_type)

        result = await session.execute(q)
        counts = {}
        for row in result.all():
            counts[row[0]] = {"count": row[1], "total_weight": float(row[2] or 0)}
        return counts

    async def _count_distinct_cultures(
        self, session: AsyncSession, canonical_type: CanonicalType, canonical_id: uuid.UUID
    ) -> int:
        """Count how many distinct cultures (not just trusted sources) back this entity.
        Implements Law 5 (Cross-Cultural Convergence)."""
        q = (
            select(func.count(distinct(SASourceRecord.culture)))
            .select_from(CanonSupportLink)
            .join(SASourceRecord, SASourceRecord.id == CanonSupportLink.archive_object_id)
            .where(
                CanonSupportLink.canonical_type == canonical_type,
                CanonSupportLink.canonical_id == canonical_id,
                SASourceRecord.culture.isnot(None),
                SASourceRecord.culture != "",
            )
        )
        try:
            result = await session.execute(q)
            return result.scalar() or 0
        except Exception:
            return 0

    async def _compute_citation_score(
        self, session: AsyncSession, canonical_type: CanonicalType,
        canonical_id: uuid.UUID, entity_time_start: int | None
    ) -> float:
        """Bidirectional citation weight (Law 4 extended).
        If a later source references an older entity, the entity gains credibility.
        E.g. Josephus (~100 CE) writing about antediluvian events boosts those events."""
        if entity_time_start is None:
            return 0.2

        q = (
            select(SASourceDate.date_start)
            .select_from(CanonSupportLink)
            .join(SASourceRecord, SASourceRecord.id == CanonSupportLink.archive_object_id)
            .join(SASourceDate, SASourceDate.source_record_id == SASourceRecord.id)
            .where(
                CanonSupportLink.canonical_type == canonical_type,
                CanonSupportLink.canonical_id == canonical_id,
                SASourceDate.date_start.isnot(None),
            )
        )
        try:
            result = await session.execute(q)
            source_dates = [row[0] for row in result.all() if row[0] is not None]
        except Exception:
            return 0.2

        if not source_dates:
            return 0.2

        later_sources = sum(1 for d in source_dates if d > entity_time_start)
        earlier_sources = sum(1 for d in source_dates if d <= entity_time_start)

        if later_sources > 0 and earlier_sources > 0:
            return min(0.5 + (later_sources * 0.15), 1.0)
        if later_sources > 0:
            return min(0.3 + (later_sources * 0.1), 0.8)
        return 0.2

    async def _compute_pattern_score(
        self, session: AsyncSession, canonical_type: CanonicalType, canonical_id: uuid.UUID
    ) -> float:
        """Pattern dominance score (Law 7).
        Entities tagged with motifs that recur across multiple independent cultures
        get a boost. Recurring structural patterns outweigh isolated claims."""
        ma_q = select(MotifAssignment.motif_id).where(
            MotifAssignment.target_type == canonical_type,
            MotifAssignment.target_id == canonical_id,
        )
        motif_ids = [row[0] for row in (await session.execute(ma_q)).all()]

        if not motif_ids:
            return 0.1

        max_culture_count = 0
        for mid in motif_ids:
            q = (
                select(func.count(distinct(SASourceRecord.culture)))
                .select_from(MotifAssignment)
                .join(CanonSupportLink, and_(
                    CanonSupportLink.canonical_type == MotifAssignment.target_type,
                    CanonSupportLink.canonical_id == MotifAssignment.target_id,
                ))
                .join(SASourceRecord, SASourceRecord.id == CanonSupportLink.archive_object_id)
                .where(
                    MotifAssignment.motif_id == mid,
                    SASourceRecord.culture.isnot(None),
                    SASourceRecord.culture != "",
                )
            )
            try:
                result = await session.execute(q)
                count = result.scalar() or 0
                max_culture_count = max(max_culture_count, count)
            except Exception:
                continue

        if max_culture_count >= 5:
            return 1.0
        if max_culture_count >= 3:
            return 0.8
        if max_culture_count >= 2:
            return 0.5
        return 0.2

    def _compute_age_score(self, time_start: int | None, time_end: int | None) -> float:
        """Older sources get higher age scores (Law 4: Age-Weighted Priority)."""
        if time_start is None and time_end is None:
            return 0.3
        ref = time_start if time_start is not None else time_end
        age = abs(ref)
        if age > 4000:
            return 1.0
        if age > 3000:
            return 0.85
        if age > 2000:
            return 0.7
        if age > 1000:
            return 0.5
        return 0.3

    def _compute_corroboration_score(self, link_counts: dict, distinct_cultures: int) -> float:
        """Corroboration with distribution independence (Law 6).
        Each culture's contribution is weighted equally — having 50 records from one
        culture does NOT outweigh 2 records from 2 separate cultures."""
        primary = link_counts.get(SupportType.PRIMARY_EVIDENCE, {}).get("count", 0)
        corroborating = link_counts.get(SupportType.CORROBORATING, {}).get("count", 0)
        secondary = link_counts.get(SupportType.SECONDARY_CONTEXT, {}).get("count", 0)
        contradicting = link_counts.get(SupportType.CONTRADICTING, {}).get("count", 0)

        total_positive = primary + corroborating + (secondary * 0.5)
        if total_positive == 0:
            return 0.1

        raw_volume = min(total_positive / 5.0, 0.7)
        culture_bonus = min(distinct_cultures * 0.15, 0.3) if distinct_cultures >= 2 else 0.0
        score = min(raw_volume + culture_bonus, 1.0)

        if contradicting > 0:
            penalty = min(contradicting * 0.1, 0.3)
            score = max(score - penalty, 0.0)
        return score

    def _compute_independence_score(self, distinct_cultures: int) -> float:
        """Cross-cultural independence (Law 5).
        Counts distinct cultures, not just distinct trusted sources.
        3+ independent cultures = maximum weight."""
        if distinct_cultures <= 0:
            return 0.1
        if distinct_cultures == 1:
            return 0.3
        if distinct_cultures == 2:
            return 0.6
        if distinct_cultures >= 3:
            return min(0.6 + (distinct_cultures * 0.1), 1.0)
        return 0.3

    def _compute_ambiguity_score(self, link_counts: dict, merge_confidence: float | None) -> float:
        """Higher ambiguity = penalty. Contradictions and low merge confidence increase ambiguity."""
        contradicting = link_counts.get(SupportType.CONTRADICTING, {}).get("count", 0)
        ambiguity = 0.0

        if contradicting > 0:
            ambiguity += min(contradicting * 0.15, 0.5)

        if merge_confidence is not None and merge_confidence < 0.5:
            ambiguity += (0.5 - merge_confidence)

        return min(ambiguity, 1.0)

    async def score_entity(
        self,
        session: AsyncSession,
        canonical_type: CanonicalType,
        canonical_id: uuid.UUID,
        time_start: int | None,
        time_end: int | None,
        merge_confidence: float | None,
    ) -> CanonScore:
        """Compute and store the 6-factor score for a single canonical entity."""
        link_counts = await self._count_support_links(session, canonical_type, canonical_id)
        distinct_cultures = await self._count_distinct_cultures(session, canonical_type, canonical_id)

        age = self._compute_age_score(time_start, time_end)
        corroboration = self._compute_corroboration_score(link_counts, distinct_cultures)
        independence = self._compute_independence_score(distinct_cultures)
        citation = await self._compute_citation_score(session, canonical_type, canonical_id, time_start)
        pattern = await self._compute_pattern_score(session, canonical_type, canonical_id)
        ambiguity = self._compute_ambiguity_score(link_counts, merge_confidence)

        final = (
            (age * AGE_WEIGHT)
            + (corroboration * CORROBORATION_WEIGHT)
            + (independence * INDEPENDENCE_WEIGHT)
            + (citation * CITATION_WEIGHT)
            + (pattern * PATTERN_WEIGHT)
            - (ambiguity * AMBIGUITY_WEIGHT)
        )
        final = max(0.0, min(1.0, final))

        existing_q = select(CanonScore).where(
            CanonScore.canonical_type == canonical_type,
            CanonScore.canonical_id == canonical_id,
        )
        existing = (await session.execute(existing_q)).scalar_one_or_none()

        if existing:
            existing.age_score = age
            existing.corroboration_score = corroboration
            existing.independence_score = independence
            existing.citation_score = citation
            existing.pattern_score = pattern
            existing.ambiguity_score = ambiguity
            existing.final_score = final
            return existing

        score = CanonScore(
            id=uuid.uuid4(),
            canonical_type=canonical_type,
            canonical_id=canonical_id,
            age_score=age,
            corroboration_score=corroboration,
            independence_score=independence,
            citation_score=citation,
            pattern_score=pattern,
            ambiguity_score=ambiguity,
            final_score=final,
        )
        session.add(score)
        return score

    async def run_full_scoring(self, session: AsyncSession) -> dict:
        """Score all current canonical entities."""
        scored = 0

        actors_q = select(CanonicalActor).where(CanonicalActor.is_current.is_(True))
        for a in (await session.execute(actors_q)).scalars().all():
            await self.score_entity(
                session, CanonicalType.ACTOR, a.id, a.time_start, a.time_end, a.merge_confidence
            )
            scored += 1

        events_q = select(CanonicalEvent).where(CanonicalEvent.is_current.is_(True))
        for e in (await session.execute(events_q)).scalars().all():
            await self.score_entity(
                session, CanonicalType.EVENT, e.id, e.time_start, e.time_end, e.merge_confidence
            )
            scored += 1

        places_q = select(CanonicalPlace).where(CanonicalPlace.is_current.is_(True))
        for p in (await session.execute(places_q)).scalars().all():
            await self.score_entity(
                session, CanonicalType.PLACE, p.id, p.time_start, p.time_end, p.merge_confidence
            )
            scored += 1

        await session.flush()
        logger.info("Scored %d canonical entities", scored)
        return {"entities_scored": scored}
