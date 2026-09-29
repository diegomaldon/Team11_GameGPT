"""Local dev launcher: `python -m api.run`.

On Windows, uvicorn creates its event loop before importing the app, so the
package-level SelectorEventLoop policy set in api/__init__.py lands too late and
psycopg's async driver blows up on the ProactorEventLoop. Setting the policy
HERE — before importing/starting uvicorn — fixes it for a plain (non-reload)
run. On Linux (the Render deploy target) the standard `uvicorn api.main:app`
start command works directly and this launcher is unnecessary.
"""

from __future__ import annotations

import asyncio
import os
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import uvicorn  # noqa: E402  (must come after the policy is set)


def main() -> None:
    uvicorn.run(
        "api.main:app",
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "8000")),
    )


if __name__ == "__main__":
    main()
