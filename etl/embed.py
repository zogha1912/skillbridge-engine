"""Embed skills and occupations with Gemini and store the vectors in pgvector.

Run with: python -m etl.embed [--kind skills|occupations|all] [--limit N]

Only rows whose embedding text or settings changed are (re-)embedded, so re-running is
cheap. Sends public taxonomy text only: never user data (see docs/04-security-and-pii.md).
"""

import argparse
import asyncio
import hashlib
import sys
import time

from google import genai
from google.genai import errors, types
from sqlalchemy import select, update

from app.core.config import get_settings
from app.db.database import AsyncSessionLocal, engine
from app.models import Occupation, Skill
from app.models.taxonomy import EMBEDDING_DIM

# gemini-embedding-2 takes the task inside the text instead of a task_type field.
# Stored taxonomy rows use the retrieval "document" format; search queries must use
# QUERY_FORMAT so both sides of a comparison are embedded consistently.
DOCUMENT_FORMAT = "title: {title} | text: {text}"
QUERY_FORMAT = "task: search result | query: {text}"
FORMAT_VERSION = "v1"
MAX_ALT_LABELS = 5
BATCH_SIZE = 50
MAX_RETRIES = 6
MAX_WAIT_SECONDS = 300


class QuotaExhausted(Exception):
    """The API's daily quota is used up; progress so far is saved."""


def embedding_text(title: str, description: str | None, alt_labels: list[str] | None) -> str:
    parts = [description.strip()] if description and description.strip() else []
    if alt_labels:
        parts.append("Also known as: " + ", ".join(alt_labels[:MAX_ALT_LABELS]))
    return DOCUMENT_FORMAT.format(title=title.strip(), text=" ".join(parts) or "none")


def embedding_hash(model: str, text: str) -> str:
    key = f"{model}|{EMBEDDING_DIM}|{FORMAT_VERSION}|{text}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


async def embed_batch(client: genai.Client, model: str, texts: list[str]) -> list[list[float]]:
    # One Content per text: a plain list of strings would be merged into a single vector.
    contents = [types.Content(parts=[types.Part.from_text(text=t)]) for t in texts]
    config = types.EmbedContentConfig(output_dimensionality=EMBEDDING_DIM)
    for attempt in range(MAX_RETRIES):
        try:
            result = await client.aio.models.embed_content(model=model, contents=contents, config=config)
            vectors = [e.values for e in result.embeddings]
            if len(vectors) != len(texts) or any(len(v) != EMBEDDING_DIM for v in vectors):
                raise RuntimeError(f"expected {len(texts)} vectors of {EMBEDDING_DIM} dims, got {len(vectors)}")
            return vectors
        except errors.APIError as exc:
            if exc.code not in (429, 500, 503) or attempt == MAX_RETRIES - 1:
                raise
            delay = retry_delay(exc) or min(2**attempt * 5, 120)
            if delay > MAX_WAIT_SECONDS:
                # A daily quota, not a per-minute one: stop instead of sleeping for hours.
                raise QuotaExhausted(f"{quota_hint(exc)}; resets in about {delay / 3600:.1f} h") from exc
            print(f"  Gemini returned {exc.code} ({quota_hint(exc)}); retrying in {delay:.0f}s", flush=True)
            await asyncio.sleep(delay)
    raise AssertionError("unreachable")


def _error_details(exc: errors.APIError) -> list[dict]:
    details = exc.details if isinstance(exc.details, dict) else {}
    return details.get("error", {}).get("details") or []


def retry_delay(exc: errors.APIError) -> float | None:
    """Seconds Google asks us to wait (RetryInfo.retryDelay, e.g. "37s"), plus a margin."""
    for item in _error_details(exc):
        if "RetryInfo" in item.get("@type", "") and str(item.get("retryDelay", "")).endswith("s"):
            return float(item["retryDelay"][:-1]) + 2
    return None


def quota_hint(exc: errors.APIError) -> str:
    for item in _error_details(exc):
        for violation in item.get("violations", []):
            if violation.get("quotaId"):
                return f"{violation['quotaId']} limit {violation.get('quotaValue', '?')}"
    return exc.status or "error"


async def embed_model_rows(client: genai.Client, model_name: str, orm_model: type, title_col: str, limit: int | None) -> int:
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(
                    orm_model.id,
                    getattr(orm_model, title_col),
                    orm_model.description,
                    orm_model.alt_labels,
                    orm_model.embedding_hash,
                ).order_by(orm_model.id)
            )
        ).all()

    todo = []
    for row_id, title, description, alt_labels, current_hash in rows:
        text = embedding_text(title, description, alt_labels)
        new_hash = embedding_hash(model_name, text)
        if new_hash != current_hash:
            todo.append((row_id, text, new_hash))
    if limit is not None:
        todo = todo[:limit]
    print(f"{orm_model.__tablename__}: {len(rows)} rows, {len(todo)} need embedding")

    done = 0
    for start in range(0, len(todo), BATCH_SIZE):
        batch = todo[start : start + BATCH_SIZE]
        vectors = await embed_batch(client, model_name, [text for _, text, _ in batch])
        async with AsyncSessionLocal() as session:
            await session.execute(
                update(orm_model),
                [
                    {"id": row_id, "embedding": vector, "embedding_hash": h}
                    for (row_id, _, h), vector in zip(batch, vectors, strict=True)
                ],
            )
            await session.commit()  # commit per batch so an interrupted run keeps its progress
        done += len(batch)
        print(f"  {done}/{len(todo)}", flush=True)
    return done


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--kind", choices=("skills", "occupations", "all"), default="all")
    parser.add_argument("--limit", type=int, help="embed at most N rows per table (for testing)")
    args = parser.parse_args(argv)

    settings = get_settings()
    if not settings.gemini_api_key or not settings.gemini_api_key.get_secret_value().strip():
        print("GEMINI_API_KEY is not set in .env")
        return 1
    client = genai.Client(api_key=settings.gemini_api_key.get_secret_value())
    model = settings.gemini_embedding_model

    started = time.monotonic()
    try:
        counts = {}
        if args.kind in ("occupations", "all"):
            counts["occupations"] = await embed_model_rows(client, model, Occupation, "title", args.limit)
        if args.kind in ("skills", "all"):
            counts["skills"] = await embed_model_rows(client, model, Skill, "preferred_label", args.limit)
    except QuotaExhausted as exc:
        print(f"Stopped: Gemini quota reached ({exc}). Progress is saved; run this command again after the reset.")
        return 2
    finally:
        await engine.dispose()
    print(f"Embedded with {model} ({EMBEDDING_DIM} dims) in {time.monotonic() - started:.0f}s: {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
