"""Import the official ESCO <-> O*NET occupation crosswalk published by the ESCO Secretariat.

Run with: python -m etl.crosswalk_import [--file path/to/crosswalk.csv]
"""

import argparse
import asyncio
import csv
import sys
from pathlib import Path

from app.db.database import AsyncSessionLocal, engine
from app.models import OccupationCrosswalk
from etl.common import DATA_DIR, download, record_import, upsert

CROSSWALK_URL = "https://esco.ec.europa.eu/system/files/2023-08/ONET_%28Occupations%29_0_updated.csv"
CROSSWALK_VERSION = "1 (Sep-22)"
HEADER_FIRST_CELL = "O*NET Id"
ESCO_OCCUPATION_PREFIX = "http://data.europa.eu/esco/occupation/"


def parse_crosswalk(lines: list[list[str]]) -> list[dict[str, str]]:
    """Skip the metadata block, then keep O*NET -> ESCO occupation rows (deduplicated)."""
    start = next(i for i, row in enumerate(lines) if row and row[0].strip() == HEADER_FIRST_CELL)
    header = [c.strip() for c in lines[start]]
    col = {name: header.index(name) for name in ("O*NET Id", "ESCO or ISCO URI", "Type of Match")}

    mappings: dict[tuple[str, str], dict[str, str]] = {}
    for row in lines[start + 1 :]:
        if len(row) < len(header):
            continue
        soc, uri, match = row[col["O*NET Id"]].strip(), row[col["ESCO or ISCO URI"]].strip(), row[col["Type of Match"]].strip()
        # Some rows point at ISCO groups rather than ESCO occupations; only occupations are used.
        if not soc or not uri.startswith(ESCO_OCCUPATION_PREFIX) or not match:
            continue
        mappings[(soc, uri)] = {"onet_soc_code": soc, "esco_uri": uri, "match_type": match}
    return list(mappings.values())


async def run(csv_path: Path) -> dict[str, int]:
    with csv_path.open(encoding="utf-8-sig", errors="replace", newline="") as f:
        rows = parse_crosswalk(list(csv.reader(f)))
    async with AsyncSessionLocal() as session:
        await upsert(session, OccupationCrosswalk, rows, ("onet_soc_code", "esco_uri"), ("match_type",))
        counts = {"mappings": len(rows)}
        await record_import(session, "esco-onet-crosswalk", CROSSWALK_VERSION, "all", csv_path, counts)
        await session.commit()
    return counts


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--file", type=Path, help="Crosswalk CSV (downloaded if omitted)")
    args = parser.parse_args(argv)

    csv_path = args.file or download(CROSSWALK_URL, DATA_DIR / "crosswalk" / "esco_onet_occupations.csv")
    try:
        counts = await run(csv_path)
    finally:
        await engine.dispose()
    print(f"ESCO-O*NET crosswalk {CROSSWALK_VERSION} imported: {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
