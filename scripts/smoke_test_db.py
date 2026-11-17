"""End-to-end database check: write, vector-search and delete a row through the app's
own engine and models. Leaves no data behind. Run with: python -m scripts.smoke_test_db"""

import asyncio
import random
import sys
from uuid import uuid4

from sqlalchemy import delete, select

from app.db.database import AsyncSessionLocal, engine
from app.models import Skill
from app.models.taxonomy import EMBEDDING_DIM


def random_unit_vector() -> list[float]:
    v = [random.uniform(-1, 1) for _ in range(EMBEDDING_DIM)]
    norm = sum(x * x for x in v) ** 0.5
    return [x / norm for x in v]


async def main() -> int:
    marker = f"smoke-test-{uuid4()}"
    target = random_unit_vector()
    # A nearby vector should come back as the nearest neighbour of `target`.
    query = [x + random.uniform(-0.01, 0.01) for x in target]

    try:
        async with AsyncSessionLocal() as session:
            session.add(
                Skill(source="onet", external_id=marker, preferred_label=marker, skill_type="smoke-test", embedding=target)
            )
            await session.commit()
        print(f"1. inserted skill '{marker}' with a {EMBEDDING_DIM}-d embedding")

        async with AsyncSessionLocal() as session:
            distance = Skill.embedding.cosine_distance(query)
            row = (
                await session.execute(
                    select(Skill.preferred_label, distance.label("distance"))
                    .where(Skill.embedding.is_not(None))
                    .order_by(distance)
                    .limit(1)
                )
            ).first()
        if row is None or row.preferred_label != marker:
            print(f"FAILED: nearest neighbour was {row!r}, expected {marker}")
            return 1
        print(f"2. pgvector nearest-neighbour search found it (cosine distance {row.distance:.6f})")
        return 0
    finally:
        async with AsyncSessionLocal() as session:
            result = await session.execute(delete(Skill).where(Skill.preferred_label == marker))
            await session.commit()
        print(f"3. cleaned up {result.rowcount} row(s)")
        await engine.dispose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
