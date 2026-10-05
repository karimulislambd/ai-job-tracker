"""Standalone worker: ``python -m app.worker`` (set RUN_WORKER_IN_API=false on the API)."""

from __future__ import annotations

import asyncio
import signal

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import SessionLocal, engine
from app.services.llm import build_llm_client
from app.worker.handlers import build_registry
from app.worker.runner import Scheduler, Worker


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    worker = Worker(SessionLocal, build_registry(build_llm_client(settings)), settings)
    scheduler = Scheduler(SessionLocal, settings)
    await asyncio.gather(worker.run_forever(stop), scheduler.run_forever(stop))
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
