"""Import O*NET occupations, skills/knowledge ratings and technology examples.

Run with: python -m etl.onet_import [--scope ict|all] [--file path/to/db_XX_X_text.zip]

Includes information from the O*NET 31.0 Database by the U.S. Department of Labor,
Employment and Training Administration (USDOL/ETA). Used under the CC BY 4.0 license.
O*NET® is a trademark of USDOL/ETA.
"""

import argparse
import asyncio
import csv
import io
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path

from app.db.database import AsyncSessionLocal, engine
from app.models import Occupation, OccupationSkill, Skill
from etl.common import DATA_DIR, download, id_map, record_import, upsert

ONET_VERSION = "31.0"
ONET_URL = f"https://www.onetcenter.org/dl_files/database/db_{ONET_VERSION.replace('.', '_')}_text.zip"

# ICT scope: computer and mathematical occupations, IT managers, computer hardware engineers.
ICT_SOC_PREFIXES = ("15-", "11-3021", "17-2061")

# Rated element files and the skill_type they map to.
RATING_FILES = {
    "Knowledge.txt": "knowledge",
    "Essential Skills.txt": "skill",
    "Transferable Skills.txt": "skill",
}
IMPORTANCE_SCALE = "IM"  # O*NET importance, 1 (not important) .. 5 (extremely important)
MIN_IMPORTANCE = 2.5  # drop elements that barely matter for the role
ESSENTIAL_IMPORTANCE = 3.5  # at or above this, treat the element as essential


@dataclass(frozen=True)
class Rating:
    soc_code: str
    element_id: str
    element_name: str
    importance: float  # rescaled to 0..1
    relation: str


def read_tsv(archive: zipfile.ZipFile, filename: str) -> list[dict[str, str]]:
    name = next(n for n in archive.namelist() if n.rsplit("/", 1)[-1] == filename)
    with archive.open(name) as f:
        return list(csv.DictReader(io.TextIOWrapper(f, encoding="utf-8"), delimiter="\t"))


def in_scope(soc_code: str, scope: str) -> bool:
    return scope == "all" or soc_code.startswith(ICT_SOC_PREFIXES)


def rescale_importance(value: float) -> float:
    """Map O*NET importance 1..5 onto 0..1."""
    return round(min(max((value - 1.0) / 4.0, 0.0), 1.0), 4)


def parse_ratings(rows: list[dict[str, str]], scope: str) -> list[Rating]:
    ratings = []
    for row in rows:
        if row["Scale ID"] != IMPORTANCE_SCALE or not in_scope(row["O*NET-SOC Code"], scope):
            continue
        if row.get("Recommend Suppress") == "Y" or row.get("Not Relevant") == "Y":
            continue
        value = float(row["Data Value"])
        if value < MIN_IMPORTANCE:
            continue
        ratings.append(
            Rating(
                soc_code=row["O*NET-SOC Code"],
                element_id=row["Element ID"],
                element_name=row["Element Name"],
                importance=rescale_importance(value),
                relation="essential" if value >= ESSENTIAL_IMPORTANCE else "optional",
            )
        )
    return ratings


def technology_key(example: str) -> str:
    return "tech:" + " ".join(example.split())


async def run(zip_path: Path, scope: str) -> dict[str, int]:
    archive = zipfile.ZipFile(zip_path)
    descriptions = {r["Element ID"]: r["Description"] for r in read_tsv(archive, "Content Model Reference.txt")}

    occupations = {
        r["O*NET-SOC Code"]: r for r in read_tsv(archive, "Occupation Data.txt") if in_scope(r["O*NET-SOC Code"], scope)
    }

    skills: dict[str, dict] = {}
    links: dict[tuple[str, str], dict] = {}
    for filename, skill_type in RATING_FILES.items():
        for rating in parse_ratings(read_tsv(archive, filename), scope):
            if rating.soc_code not in occupations:
                continue
            skills[rating.element_id] = {
                "source": "onet",
                "external_id": rating.element_id,
                "preferred_label": rating.element_name,
                "description": descriptions.get(rating.element_id),
                "skill_type": skill_type,
            }
            links[(rating.soc_code, rating.element_id)] = {
                "relation": rating.relation,
                "importance": rating.importance,
            }

    for row in read_tsv(archive, "Software Skills.txt"):
        soc = row["O*NET-SOC Code"]
        if soc not in occupations:
            continue
        key = technology_key(row["Workplace Example"])
        skills.setdefault(
            key,
            {
                "source": "onet",
                "external_id": key,
                "preferred_label": " ".join(row["Workplace Example"].split()),
                "description": f"Technology: {row['Element Name']}",
                "skill_type": "technology",
            },
        )
        # Technology examples carry no importance rating; the engine weights them as optional.
        links.setdefault((soc, key), {"relation": "optional", "importance": None})

    async with AsyncSessionLocal() as session:
        await upsert(
            session,
            Occupation,
            [
                {"source": "onet", "external_id": soc, "code": soc, "title": r["Title"], "description": r["Description"]}
                for soc, r in occupations.items()
            ],
            conflict_cols=("source", "external_id"),
            update_cols=("code", "title", "description"),
        )
        await upsert(
            session,
            Skill,
            list(skills.values()),
            conflict_cols=("source", "external_id"),
            update_cols=("preferred_label", "description", "skill_type"),
        )
        occ_ids = await id_map(session, Occupation, "onet", occupations)
        skill_ids = await id_map(session, Skill, "onet", skills)
        await upsert(
            session,
            OccupationSkill,
            [
                {
                    "occupation_id": occ_ids[soc],
                    "skill_id": skill_ids[key],
                    "source": "onet",
                    **link,
                }
                for (soc, key), link in links.items()
            ],
            conflict_cols=("occupation_id", "skill_id"),
            update_cols=("relation", "importance", "source"),
        )
        counts = {
            "occupations": len(occupations),
            "skills": sum(1 for s in skills.values() if s["skill_type"] != "technology"),
            "technologies": sum(1 for s in skills.values() if s["skill_type"] == "technology"),
            "occupation_skills": len(links),
        }
        await record_import(session, "onet", ONET_VERSION, scope, zip_path, counts)
        await session.commit()
    return counts


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scope", choices=("ict", "all"), default="ict")
    parser.add_argument("--file", type=Path, help="O*NET text zip (downloaded if omitted)")
    args = parser.parse_args(argv)

    zip_path = args.file or download(ONET_URL, DATA_DIR / "onet" / Path(ONET_URL).name)
    try:
        counts = await run(zip_path, args.scope)
    finally:
        await engine.dispose()
    print(f"O*NET {ONET_VERSION} ({args.scope}) imported: {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
