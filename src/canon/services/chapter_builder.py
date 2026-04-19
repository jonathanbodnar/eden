"""Chapter-builder: groups canonical objects into time-banded chapters within epochs."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.canon.models.canonical_actor import CanonicalActor
from src.canon.models.canonical_chapter import CanonicalChapter
from src.canon.models.canonical_epoch import CanonicalEpoch
from src.canon.models.canonical_event import CanonicalEvent
from src.canon.models.canonical_place import CanonicalPlace
from src.canon.models.canon_dependency import CanonDependency
from src.canon.models.enums import CanonicalType

logger = logging.getLogger(__name__)

DEFAULT_EPOCHS = [
    {
        "title": "The Beginning — Creation of the World",
        "time_start": None, "time_end": None,
        "summary": "How the world began according to every ancient tradition: "
                   "Sumerian, Egyptian, Hebrew, Hindu, Chinese, Greek, Norse, "
                   "Zoroastrian, Mayan, and countless others.",
    },
    {
        "title": "Age of the Gods",
        "time_start": None, "time_end": None,
        "summary": "When the gods walked the earth, established divine order, "
                   "and shaped the cosmos across every ancient civilization.",
    },
    {
        "title": "Before the Flood — The Antediluvian World",
        "time_start": None, "time_end": None,
        "summary": "The world before the great deluge: antediluvian rulers, "
                   "patriarchs, ancient sages, and the first races.",
    },
    {
        "title": "The Great Flood",
        "time_start": None, "time_end": None,
        "summary": "The near-universal flood narrative from over 200 cultures: "
                   "Ziusudra, Noah, Manu, Deucalion, Nüwa, and more.",
    },
    {
        "title": "Dawn of Civilization",
        "time_start": -12000, "time_end": -5000,
        "summary": "The earliest built structures and settlements. "
                   "Göbekli Tepe, Çatalhöyük, earliest agriculture.",
    },
    {
        "title": "Rise of the First Cities",
        "time_start": -5000, "time_end": -3000,
        "summary": "Eridu, Uruk, first Sumerian city-states. "
                   "Pre-dynastic Egypt. Early Indus settlements.",
    },
    {
        "title": "Age of Empires",
        "time_start": -3000, "time_end": -2000,
        "summary": "Akkadian Empire, Egyptian Old Kingdom, Indus Valley, "
                   "Ur III dynasty. The first great empires.",
    },
    {
        "title": "Age of Heroes",
        "time_start": -2000, "time_end": -1200,
        "summary": "Hammurabi's Babylon, Egyptian New Kingdom, Hittites, "
                   "Shang Dynasty, Mycenaean Greece, the Trojan War.",
    },
    {
        "title": "Age of Iron and Prophets",
        "time_start": -1200, "time_end": -500,
        "summary": "Neo-Assyrian/Neo-Babylonian empires, Hebrew prophets, "
                   "Zhou Dynasty, Homer's Greece, Zoroaster.",
    },
    {
        "title": "The Classical World",
        "time_start": -500, "time_end": 100,
        "summary": "The Axial Age: Buddha, Confucius, Greek philosophers, "
                   "Alexander, Maurya Empire, Rome, Qin/Han dynasties.",
    },
    {
        "title": "Undated Traditions",
        "time_start": None, "time_end": None,
        "summary": "Oral traditions, myths, and accounts that cannot be "
                   "placed in a specific time period.",
    },
]

CHAPTER_BAND_SIZE = 500


@dataclass
class CanonItem:
    id: uuid.UUID
    canonical_type: CanonicalType
    name: str
    time_start: int | None
    time_end: int | None


class ChapterBuilderService:

    async def ensure_epochs(self, session: AsyncSession) -> list[CanonicalEpoch]:
        """Create default epochs if none exist."""
        q = select(CanonicalEpoch).where(CanonicalEpoch.is_current.is_(True))
        existing = (await session.execute(q)).scalars().all()
        if existing:
            return list(existing)

        epochs = []
        for ep_def in DEFAULT_EPOCHS:
            epoch = CanonicalEpoch(
                id=uuid.uuid4(),
                title=ep_def["title"],
                time_start=ep_def["time_start"],
                time_end=ep_def["time_end"],
                summary=ep_def.get("summary"),
                version=1,
                is_current=True,
            )
            session.add(epoch)
            epochs.append(epoch)

        await session.flush()
        logger.info("Created %d default epochs", len(epochs))
        return epochs

    async def gather_all_canon_items(self, session: AsyncSession) -> list[CanonItem]:
        items = []

        actors_q = select(CanonicalActor).where(CanonicalActor.is_current.is_(True))
        for a in (await session.execute(actors_q)).scalars().all():
            items.append(CanonItem(a.id, CanonicalType.ACTOR, a.canonical_name, a.time_start, a.time_end))

        events_q = select(CanonicalEvent).where(CanonicalEvent.is_current.is_(True))
        for e in (await session.execute(events_q)).scalars().all():
            items.append(CanonItem(e.id, CanonicalType.EVENT, e.canonical_name, e.time_start, e.time_end))

        places_q = select(CanonicalPlace).where(CanonicalPlace.is_current.is_(True))
        for p in (await session.execute(places_q)).scalars().all():
            items.append(CanonItem(p.id, CanonicalType.PLACE, p.canonical_name, p.time_start, p.time_end))

        return items

    def assign_to_epoch(
        self, item: CanonItem, epochs: list[CanonicalEpoch]
    ) -> CanonicalEpoch:
        """Assign a canon item to the best-matching epoch by time range."""
        if item.time_start is None and item.time_end is None:
            for ep in epochs:
                if ep.time_start is None and ep.time_end is None:
                    return ep
            return epochs[-1]

        ref_time = item.time_start if item.time_start is not None else item.time_end

        for ep in epochs:
            if ep.time_start is None and ep.time_end is None:
                continue
            ep_start = ep.time_start if ep.time_start is not None else -999999
            ep_end = ep.time_end if ep.time_end is not None else 999999
            if ep_start <= ref_time <= ep_end:
                return ep

        for ep in epochs:
            if ep.time_start is None and ep.time_end is None:
                return ep
        return epochs[-1]

    def _chapter_band_key(self, item: CanonItem) -> int | None:
        """Compute a time band for sub-epoch chapter grouping."""
        ref = item.time_start if item.time_start is not None else item.time_end
        if ref is None:
            return None
        return (ref // CHAPTER_BAND_SIZE) * CHAPTER_BAND_SIZE

    async def build_chapters(self, session: AsyncSession) -> list[CanonicalChapter]:
        """Build chapters from canonical items, organized by epoch and time band."""
        epochs = await self.ensure_epochs(session)
        items = await self.gather_all_canon_items(session)

        epoch_items: dict[uuid.UUID, list[CanonItem]] = {ep.id: [] for ep in epochs}
        epoch_map = {ep.id: ep for ep in epochs}

        for item in items:
            ep = self.assign_to_epoch(item, epochs)
            epoch_items[ep.id].append(item)

        chapters = []
        for epoch_id, ep_items in epoch_items.items():
            if not ep_items:
                continue

            bands: dict[int | None, list[CanonItem]] = {}
            for it in ep_items:
                band = self._chapter_band_key(it)
                bands.setdefault(band, []).append(it)

            sorted_bands = sorted(bands.keys(), key=lambda x: x if x is not None else 999999)

            for order, band_key in enumerate(sorted_bands):
                band_items = bands[band_key]
                ep = epoch_map[epoch_id]

                if band_key is not None:
                    t_start = band_key
                    t_end = band_key + CHAPTER_BAND_SIZE
                    title = f"{ep.title}: {abs(t_start)}-{abs(t_end)} {'BCE' if t_start < 0 else 'CE'}"
                else:
                    t_start = ep.time_start
                    t_end = ep.time_end
                    title = f"{ep.title}: General"

                actor_names = [i.name for i in band_items if i.canonical_type == CanonicalType.ACTOR][:5]
                event_names = [i.name for i in band_items if i.canonical_type == CanonicalType.EVENT][:5]

                summary_parts = []
                if actor_names:
                    summary_parts.append(f"Key figures: {', '.join(actor_names)}")
                if event_names:
                    summary_parts.append(f"Key events: {', '.join(event_names)}")

                chapter = CanonicalChapter(
                    id=uuid.uuid4(),
                    epoch_id=epoch_id,
                    title=title,
                    time_start=t_start,
                    time_end=t_end,
                    chapter_summary=". ".join(summary_parts) if summary_parts else None,
                    chapter_order=order,
                    version=1,
                    is_current=True,
                )
                session.add(chapter)
                chapters.append(chapter)

                for it in band_items:
                    dep = CanonDependency(
                        id=uuid.uuid4(),
                        parent_type=CanonicalType.CHAPTER,
                        parent_id=chapter.id,
                        child_type=it.canonical_type,
                        child_id=it.id,
                    )
                    session.add(dep)

        await session.flush()
        logger.info("Built %d chapters across %d epochs", len(chapters), len(epochs))
        return chapters

    async def run_ensure_epochs_only(self, session: AsyncSession) -> dict:
        """Create the default epoch set without building chapters. Fast, no AI."""
        epochs = await self.ensure_epochs(session)
        return {"epochs": len(epochs), "chapters": 0}

    async def run_full_build(self, session: AsyncSession) -> dict:
        """Build chapters for all epochs (ensure_epochs is called inside build_chapters)."""
        chapters = await self.build_chapters(session)
        epoch_q = select(CanonicalEpoch).where(CanonicalEpoch.is_current.is_(True))
        epoch_count = len((await session.execute(epoch_q)).scalars().all())
        return {
            "epochs": epoch_count,
            "chapters": len(chapters),
        }
