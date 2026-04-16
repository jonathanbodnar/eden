"""Re-run Stage 5 post-processing on existing story_chapters (v2).

Reads each chapter's clusters + archetypes and re-applies scrub_leaked_names
+ insert_annotations. Updates narrative_text in place. Use when Stage 5 logic
changed but Stage 1-4 artifacts are fine.

Run:
    python -m scripts.reprocess_chapter_postprocess [--chapter-number N]
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from sqlalchemy import select

from src.canon.database import async_session_factory
from src.canon.models.narrative_v2 import EventCluster
from src.canon.models.story_outline import StoryOutline
from src.canon.services.narrative_v2.stage4_render import render_chapter  # unused but ensures imports ok
from src.canon.services.narrative_v2.stage5_post_process import (
    insert_annotations,
    load_archetypes_by_name,
    scrub_leaked_names,
    validate,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
logger = logging.getLogger("reprocess_pp")


async def _reprocess_one(session, outline_id, chapter_id):
    # Get existing chapter
    ch = (
        await session.execute(
            select_chapter_model(chapter_id)
        )
    ).scalar_one_or_none()
    if ch is None:
        logger.warning("No chapter found for %s", chapter_id)
        return
    # Load clusters
    clusters = (
        await session.execute(
            select(EventCluster)
            .where(EventCluster.story_outline_id == outline_id)
            .order_by(EventCluster.seq)
        )
    ).scalars().all()
    if not clusters:
        logger.warning("No clusters for outline %s", outline_id)
        return

    archetype_names = [c.primary_archetype_name for c in clusters if c.primary_archetype_name]
    archetypes = await load_archetypes_by_name(session, archetype_names)

    # Original narrative is pre-annotation; strip the [[actor:X]] tags first so
    # we can re-scrub cleanly.
    import re
    raw = re.sub(r"\[\[(?:actor|place):([^\]]+)\]\]", r"\1", ch.narrative_text or "")

    cleaned = scrub_leaked_names(raw, archetypes)
    cleaned = insert_annotations(cleaned, archetypes)
    problems = validate(cleaned, archetypes)

    ch.narrative_text = cleaned
    await session.commit()
    logger.info(
        "Reprocessed chapter %s (%d chars, %d archetypes, %d problems)",
        chapter_id,
        len(cleaned),
        len(archetypes),
        len(problems),
    )
    if problems:
        logger.info("  problems: %s", problems)


def select_chapter_model(chapter_id):
    from src.canon.models.story_chapter import StoryChapter
    return select(StoryChapter).where(StoryChapter.id == chapter_id)


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--chapter-number", type=int, default=None, help="Only process this chapter number")
    args = parser.parse_args()

    from src.canon.models.story_chapter import StoryChapter

    async with async_session_factory() as session:
        q = (
            select(StoryChapter.id, StoryChapter.story_outline_id, StoryOutline.chapter_number)
            .join(StoryOutline, StoryOutline.id == StoryChapter.story_outline_id)
            .where(StoryChapter.pipeline_version == "v2")
            .order_by(StoryOutline.chapter_number)
        )
        rows = (await session.execute(q)).all()

    for row in rows:
        if args.chapter_number is not None and row.chapter_number != args.chapter_number:
            continue
        logger.info("== Chapter %s ==", row.chapter_number)
        async with async_session_factory() as s:
            await _reprocess_one(s, row.story_outline_id, row.id)


if __name__ == "__main__":
    asyncio.run(main())
