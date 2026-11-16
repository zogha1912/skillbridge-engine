"""Check the database connection. Run with: python -m scripts.check_db"""

import asyncio
import sys

from sqlalchemy import text

from app.db.database import engine


async def main() -> int:
    try:
        async with engine.connect() as conn:
            user = (await conn.execute(text("SELECT current_user"))).scalar()
            db = (await conn.execute(text("SELECT current_database()"))).scalar()
            version = (await conn.execute(text("SHOW server_version"))).scalar()
            vector = (
                await conn.execute(
                    text(
                        "SELECT default_version, installed_version "
                        "FROM pg_available_extensions WHERE name = 'vector'"
                    )
                )
            ).first()
    except Exception as exc:
        print(f"FAILED to connect: {type(exc).__name__}: {exc}")
        return 1
    finally:
        await engine.dispose()

    print(f"Connected as '{user}' to database '{db}' (PostgreSQL {version})")
    if vector is None:
        print("pgvector: NOT available on this server")
        return 1
    if vector.installed_version:
        print(f"pgvector: installed ({vector.installed_version})")
    else:
        print("pgvector: available, not installed yet; `alembic upgrade head` installs it")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
