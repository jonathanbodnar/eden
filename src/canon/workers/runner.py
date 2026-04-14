"""Worker runner - starts all or specific worker loops."""

from __future__ import annotations

import asyncio
import logging
import signal
import sys

from src.canon.workers.canon_synth_worker import CanonSynthWorker
from src.canon.workers.canon_update_worker import CanonUpdateWorker
from src.canon.workers.chapter_build_worker import ChapterBuildWorker
from src.canon.workers.knowledge_prep_worker import KnowledgePrepWorker
from src.canon.workers.narration_worker import NarrationWorker
from src.canon.workers.video_worker import VideoFullWorker, VideoScriptWorker
from src.canon.workers.world_packet_worker import WorldPacketWorker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)

WORKER_CLASSES = {
    "knowledge_prep": KnowledgePrepWorker,
    "canon_synth": CanonSynthWorker,
    "chapter_build": ChapterBuildWorker,
    "narration": NarrationWorker,
    "world_packet": WorldPacketWorker,
    "canon_update": CanonUpdateWorker,
    "video_script": VideoScriptWorker,
    "video_full": VideoFullWorker,
}


async def main(worker_names: list[str]):
    workers = []
    for name in worker_names:
        cls = WORKER_CLASSES.get(name)
        if cls is None:
            logger.error("Unknown worker: %s. Available: %s", name, list(WORKER_CLASSES.keys()))
            sys.exit(1)
        workers.append(cls())

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda: [w.stop() for w in workers])

    logger.info("Starting %d workers: %s", len(workers), [w.worker_id for w in workers])
    await asyncio.gather(*[w.run_loop() for w in workers])


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] == "all":
        names = list(WORKER_CLASSES.keys())
    else:
        names = args

    asyncio.run(main(names))
