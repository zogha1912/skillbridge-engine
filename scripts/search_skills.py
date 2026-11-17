"""Semantic skill search over the embedded taxonomy.

Run with: python -m scripts.search_skills "FastAPI" [--limit 10] [--occupations]
"""

import argparse
import asyncio
import sys

from google import genai
from google.genai import types
from sqlalchemy import select

from app.core.config import get_settings
from app.db.database import AsyncSessionLocal, engine
from app.models import Occupation, Skill
from app.models.taxonomy import EMBEDDING_DIM
from etl.embed import QUERY_FORMAT


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("query")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--occupations", action="store_true", help="search job roles instead of skills")
    args = parser.parse_args(argv)

    settings = get_settings()
    client = genai.Client(api_key=settings.gemini_api_key.get_secret_value())
    result = await client.aio.models.embed_content(
        model=settings.gemini_embedding_model,
        contents=[types.Content(parts=[types.Part.from_text(text=QUERY_FORMAT.format(text=args.query))])],
        config=types.EmbedContentConfig(output_dimensionality=EMBEDDING_DIM),
    )
    query_vector = result.embeddings[0].values

    model = Occupation if args.occupations else Skill
    label = model.title if args.occupations else model.preferred_label
    kind = model.code if args.occupations else model.skill_type
    distance = model.embedding.cosine_distance(query_vector)
    try:
        async with AsyncSessionLocal() as session:
            rows = (
                await session.execute(
                    select(label, model.source, kind, (1 - distance).label("similarity"))
                    .where(model.embedding.is_not(None))
                    .order_by(distance)
                    .limit(args.limit)
                )
            ).all()
    finally:
        await engine.dispose()

    print(f'Nearest {"roles" if args.occupations else "skills"} to "{args.query}":')
    for name, source, extra, similarity in rows:
        print(f"  {similarity:.3f}  [{source}] {name}  ({extra})")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
