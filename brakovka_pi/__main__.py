from __future__ import annotations

import asyncio

from .controller import main, setup_logging

__all__ = ["main", "setup_logging"]

if __name__ == "__main__":
    setup_logging()
    asyncio.run(main())
