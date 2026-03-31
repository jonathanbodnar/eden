"""Worker runner: starts pipeline workers in the background."""

from __future__ import annotations

import asyncio
import logging
import signal
import sys

from src.ingestion.workers.discovery_worker import DiscoveryWorker
from src.ingestion.workers.embedding_worker import EmbeddingWorker
from src.ingestion.workers.fetch_worker import FetchWorker
from src.ingestion.workers.normalization_worker import NormalizationWorker
from src.ingestion.workers.segmentation_worker import SegmentationWorker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

WORKER_CLASSES = [
    DiscoveryWorker,
    FetchWorker,
    NormalizationWorker,
    SegmentationWorker,
    EmbeddingWorker,
]


async def run_all_workers() -> None:
    workers = [cls() for cls in WORKER_CLASSES]
    tasks = []

    def shutdown():
        logger.info("Shutdown signal received, stopping workers...")
        for w in workers:
            w.stop()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, shutdown)

    for worker in workers:
        tasks.append(asyncio.create_task(worker.run_loop()))
        logger.info("Started %s", worker.worker_id)

    await asyncio.gather(*tasks, return_exceptions=True)


def main():
    worker_type = sys.argv[1] if len(sys.argv) > 1 else "all"

    if worker_type == "all":
        asyncio.run(run_all_workers())
    else:
        worker_map = {
            "discovery": DiscoveryWorker,
            "fetch": FetchWorker,
            "normalize": NormalizationWorker,
            "segment": SegmentationWorker,
            "embed": EmbeddingWorker,
        }
        cls = worker_map.get(worker_type)
        if not cls:
            print(f"Unknown worker type: {worker_type}")
            print(f"Available: {', '.join(worker_map.keys())}, all")
            sys.exit(1)

        worker = cls()

        def shutdown():
            worker.stop()

        loop = asyncio.new_event_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, shutdown)

        loop.run_until_complete(worker.run_loop())


if __name__ == "__main__":
    main()
