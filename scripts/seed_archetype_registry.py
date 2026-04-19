"""Seed the archetype_registry with core archetypes.

Populates the global registry with ~20 well-established archetypes that span
multiple cultures. Chapters will find these via direct AKA lookup and reuse
them rather than minting duplicates on the fly.

Run:
    python -m scripts.seed_archetype_registry
"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.canon.database import async_session_factory
from src.canon.models.narrative_v2 import ArchetypeRegistry

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
logger = logging.getLogger("seed_archetypes")


# (archetype_name, role_description, entity_type, aka_names)
CORE_ARCHETYPES: list[tuple[str, str, str, list[str]]] = [
    (
        "The Primordial Void",
        "the formless state before creation",
        "actor",
        ["Void", "Chaos", "Tohu wa-bohu", "Ginnungagap", "Hundun", "Abyss"],
    ),
    (
        "The Primordial Waters",
        "the undifferentiated deep from which creation emerges",
        "actor",
        ["Nu", "Nun", "Apsu", "Tehom", "Tiamat", "Ginnungagap", "Salt Waters"],
    ),
    (
        "The First Creator",
        "the self-existent being whose word or desire begins creation",
        "actor",
        [
            "Atum", "Khepera", "Ptah",
            "Brahma", "Hiranyagarbha", "Prajapati",
            "Pangu",
            "Elohim", "YHWH", "Yahweh",
            "Mbombo", "Olodumare",
        ],
    ),
    (
        "The Divine Craftsman",
        "shapes matter into beings, especially humanity",
        "actor",
        ["Enki", "Ea", "Khnum", "Ptah", "Prometheus", "Ilmarinen", "Goibniu"],
    ),
    (
        "The Sky Father",
        "the supreme god of the heavens and firmament",
        "actor",
        ["Anu", "An", "Zeus", "Jupiter", "Dyaus Pita", "Tian", "Tengri", "Horus"],
    ),
    (
        "The Earth Mother",
        "the primordial female principle of the earth",
        "actor",
        ["Ki", "Gaia", "Tellus", "Prithvi", "Papatuanuku", "Terra"],
    ),
    (
        "The Sun God",
        "the personified sun, often daily reborn",
        "actor",
        ["Ra", "Re", "Shamash", "Utu", "Surya", "Helios", "Sol", "Apollo", "Khepera"],
    ),
    (
        "The Moon God",
        "the personified moon",
        "actor",
        ["Sin", "Nanna", "Thoth", "Iah", "Chandra", "Selene", "Mani"],
    ),
    (
        "The Mother of All Living",
        "shapes or births the first generations of humanity",
        "actor",
        ["Aruru", "Ninhursag", "Belet-ili", "Mami", "Nammu", "Nuwa", "Eve"],
    ),
    (
        "The Mother of Chaos",
        "the monstrous primordial feminine defeated at creation",
        "actor",
        ["Tiamat", "Omuroca", "Thalatth", "Leviathan", "Rahab"],
    ),
    (
        "The Shining Ones",
        "the collective body of high gods or sky beings",
        "actor",
        ["Anunnaki", "Igigi", "Devas", "Aesir", "Vanir", "Elohim", "Netjeru"],
    ),
    (
        "The First Man",
        "the first human being",
        "actor",
        ["Adam", "Adapa", "Manu", "Yima", "Ask", "Askr", "Ymir", "Purusha"],
    ),
    (
        "The First Woman",
        "the first human female",
        "actor",
        ["Eve", "Embla", "Pandora", "Shatarupa"],
    ),
    (
        "The Flood Hero",
        "the righteous man warned before the deluge",
        "actor",
        ["Ziusudra", "Utnapishtim", "Atrahasis", "Noah", "Manu", "Deucalion"],
    ),
    (
        "The Trickster",
        "the boundary-crossing deceiver and culture-bringer",
        "actor",
        ["Enki", "Loki", "Hermes", "Prometheus", "Coyote", "Anansi", "Set"],
    ),
    (
        "The Champion",
        "the storm-wielding warrior god who defeats chaos",
        "actor",
        ["Marduk", "Ninurta", "Baal", "Thor", "Indra", "Teshub"],
    ),
    (
        "The Serpent Adversary",
        "the chaos-serpent opposing order",
        "actor",
        ["Apep", "Apophis", "Jörmungandr", "Leviathan", "Vritra", "Typhon"],
    ),
    (
        "The Garden of Beginning",
        "the fertile paradise where the first humans dwell",
        "place",
        ["Eden", "Dilmun", "Uttarakuru", "Elysium", "Tír na nÓg"],
    ),
    (
        "The First City",
        "the earliest human settlement where kingship descends",
        "place",
        ["Eridu", "Uruk", "Erech", "Kish", "Memphis", "Enoch"],
    ),
    (
        "The Mountain of the Gods",
        "the axis mundi where gods dwell and assemble",
        "place",
        ["Olympus", "Mount Meru", "Sinai", "Zaphon", "Mount Sumeru", "Kunlun"],
    ),
]


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


async def _find_canonical_ids_for_names(
    session: AsyncSession, names: list[str], entity_type: str
) -> list[uuid.UUID]:
    table = "canonical_actors" if entity_type == "actor" else "canonical_places"
    ids: list[uuid.UUID] = []
    seen: set[str] = set()
    for name in names:
        if not name:
            continue
        rows = (
            await session.execute(
                text(
                    f"SELECT id FROM {table} "
                    f"WHERE LOWER(canonical_name) = :n AND is_current = true "
                    f"LIMIT 5"
                ),
                {"n": name.strip().lower()},
            )
        ).all()
        for (cid,) in rows:
            if str(cid) not in seen:
                seen.add(str(cid))
                ids.append(cid)
    return ids


async def seed() -> None:
    async with async_session_factory() as session:
        existing_names = {
            r
            for r in (
                await session.execute(select(ArchetypeRegistry.archetype_name))
            )
            .scalars()
            .all()
        }
        logger.info(
            "Found %d existing archetypes; seeding new ones", len(existing_names)
        )

        created = 0
        for name, desc, entity_type, aka_names in CORE_ARCHETYPES:
            if name in existing_names:
                continue
            canonical_ids = await _find_canonical_ids_for_names(
                session, aka_names, entity_type
            )
            row = ArchetypeRegistry(
                archetype_name=name,
                role_description=desc,
                entity_type=entity_type,
                also_known_as=aka_names,
                canonical_ids=canonical_ids,
                role_signature={"seeded": True},
                usage_count=0,
            )
            session.add(row)
            created += 1
            logger.info("  + %s (%d canonical IDs)", name, len(canonical_ids))

        await session.commit()
        logger.info("Seeded %d new archetypes", created)


if __name__ == "__main__":
    asyncio.run(seed())
