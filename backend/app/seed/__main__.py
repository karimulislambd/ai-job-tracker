"""``python -m app.seed [--force]`` — seed the demo template account."""

from __future__ import annotations

import argparse
import asyncio

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import SessionLocal, engine
from app.seed.seeder import seed_demo_template


async def _main(force: bool) -> None:
    async with SessionLocal() as session:
        user = await seed_demo_template(session, force=force)
        print(f"demo template ready: {user.email} ({user.id})")
    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="re-create the template from scratch")
    args = parser.parse_args()
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    asyncio.run(_main(args.force))
