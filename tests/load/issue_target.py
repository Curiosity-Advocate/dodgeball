"""Resolve the seeded match and a scorekeeper token for the k6 load harness.

Run after `app.seed`; prints `match_id=...` and `token=...` lines for the
workflow to capture into $GITHUB_OUTPUT.
"""

import asyncio

from sqlalchemy import text

from app.auth.tokens import create_access_token
from app.core.db import get_engine
from app.seed import DEMO_EMAIL


async def main() -> None:
    engine = get_engine()
    async with engine.connect() as conn:
        user_id = (
            await conn.execute(text("SELECT id FROM users WHERE email = :e"), {"e": DEMO_EMAIL})
        ).scalar_one()
        match_id = (
            await conn.execute(
                text("SELECT match_id FROM match_scorekeepers WHERE user_id = :u LIMIT 1"),
                {"u": user_id},
            )
        ).scalar_one()
    await engine.dispose()
    print(f"match_id={match_id}")
    print(f"token={create_access_token(str(user_id), 'scorekeeper')}")


if __name__ == "__main__":
    asyncio.run(main())
