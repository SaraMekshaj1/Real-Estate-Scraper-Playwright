from __future__ import annotations
import asyncio
from app.container.container import Container
from dotenv import load_dotenv

load_dotenv()


async def _run() -> None:
    container = Container()
    client = container.client()
    engine = container.scraper_engine()

    try:
        # warmup() only exists on BrowserClient — harmless no-op check
        # so the same main.py works for either client_mode.
        if hasattr(client, "warmup"):
            await client.warmup(container.settings.base_url)
        await engine.run()
    finally:
        await client.close()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
