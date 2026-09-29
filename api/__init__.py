"""GameGPT API package.

Windows integration fix: psycopg's async connections cannot run on the default
ProactorEventLoop, so on Windows we install the SelectorEventLoop policy at
import time — before uvicorn, the seed scripts, or pytest create a loop. No-op
on Linux/macOS (the deploy targets), so production is unaffected.
"""

import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
