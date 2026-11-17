"""Helpers shared by the taxonomy importers: downloads, checksums and batched upserts."""

import hashlib
import shutil
import urllib.request
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from sqlalchemy import select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import TaxonomyImport

DATA_DIR = Path("data/raw")
BATCH_SIZE = 1000


def download(url: str, dest: Path) -> Path:
    """Download url to dest unless it already exists. Writes to a temp file first."""
    if dest.exists():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": "skillbridge-engine-etl"})
    with urllib.request.urlopen(request, timeout=120) as response, tmp.open("wb") as out:
        shutil.copyfileobj(response, out)
    tmp.replace(dest)
    return dest


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def batched(rows: Sequence[dict[str, Any]], size: int = BATCH_SIZE) -> Iterable[Sequence[dict[str, Any]]]:
    for start in range(0, len(rows), size):
        yield rows[start : start + size]


async def upsert(
    session: AsyncSession,
    model: type,
    rows: Sequence[dict[str, Any]],
    conflict_cols: Sequence[str],
    update_cols: Sequence[str],
) -> int:
    """INSERT ... ON CONFLICT DO UPDATE in batches. Rows must be unique on conflict_cols."""
    for batch in batched(rows):
        stmt = insert(model).values(list(batch))
        if update_cols:
            stmt = stmt.on_conflict_do_update(
                index_elements=list(conflict_cols),
                set_={col: stmt.excluded[col] for col in update_cols},
            )
        else:
            stmt = stmt.on_conflict_do_nothing(index_elements=list(conflict_cols))
        await session.execute(stmt)
    return len(rows)


async def id_map(session: AsyncSession, model: type, source: str, external_ids: Iterable[str]) -> dict[str, int]:
    """Map external_id -> primary key for rows of one source."""
    wanted = list(set(external_ids))
    result: dict[str, int] = {}
    for start in range(0, len(wanted), BATCH_SIZE):
        chunk = wanted[start : start + BATCH_SIZE]
        rows = await session.execute(
            select(model.external_id, model.id).where(
                tuple_(model.source, model.external_id).in_([(source, e) for e in chunk])
            )
        )
        result.update({external_id: pk for external_id, pk in rows})
    return result


async def record_import(
    session: AsyncSession, source: str, version: str, scope: str, file_path: Path, counts: dict[str, int]
) -> None:
    session.add(
        TaxonomyImport(source=source, version=version, scope=scope, file_sha256=sha256_file(file_path), row_counts=counts)
    )
