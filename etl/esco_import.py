"""Import ESCO occupations, skills and essential/optional occupation-skill relations.

Run with: python -m etl.esco_import [--scope ict|all] [--file path/to/esco_csv.zip]

The ESCO CSV package is requested by email from https://esco.ec.europa.eu/en/use-esco/download
(Version v1.2.1, Content: classification, Language: en, File type: csv); save the zip as
data/raw/esco/esco_v1.2.1_en_csv.zip or pass --file.

This service uses the ESCO classification of the European Commission. The imported data
is a modified version: it is filtered by scope and restructured.
"""

import argparse
import asyncio
import csv
import io
import sys
import zipfile
from pathlib import Path

from app.db.database import AsyncSessionLocal, engine
from app.models import Occupation, OccupationSkill, Skill
from etl.common import DATA_DIR, id_map, record_import, upsert

ESCO_VERSION = "1.2.1"
DEFAULT_ZIP = DATA_DIR / "esco" / f"esco_v{ESCO_VERSION}_en_csv.zip"

# ICT scope by ISCO-08 group: ICT professionals (25), ICT operations and user support
# technicians (351), ICT service managers (1330).
ICT_ISCO_PREFIXES = ("25", "351", "1330")
SKILL_TYPES = {"skill/competence": "skill", "knowledge": "knowledge"}


def read_csv(archive: zipfile.ZipFile, filename: str) -> list[dict[str, str]]:
    with archive.open(filename) as f:
        return list(csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig")))


def in_scope(isco_group: str, scope: str) -> bool:
    return scope == "all" or isco_group.startswith(ICT_ISCO_PREFIXES)


def split_labels(raw: str) -> list[str] | None:
    """ESCO packs alternative labels into one newline-separated cell."""
    labels = list(dict.fromkeys(label.strip() for label in raw.splitlines() if label.strip()))
    return labels or None


def map_skill_type(raw: str) -> str | None:
    return SKILL_TYPES.get(raw.strip())


def select_rows(
    occupations: list[dict[str, str]],
    skills: list[dict[str, str]],
    relations: list[dict[str, str]],
    digital_skill_uris: set[str],
    scope: str,
) -> tuple[list[dict], list[dict], list[dict]]:
    """Pick in-scope occupations, the skills they use (plus digital skills), and their links."""
    occ_rows = {
        o["conceptUri"]: {
            "source": "esco",
            "external_id": o["conceptUri"],
            "code": o["code"] or None,
            "title": o["preferredLabel"],
            "alt_labels": split_labels(o["altLabels"]),
            "description": o["description"] or None,
        }
        for o in occupations
        if o["status"] == "released" and in_scope(o["iscoGroup"], scope)
    }

    links: dict[tuple[str, str], dict] = {}
    for r in relations:
        if r["occupationUri"] in occ_rows and r["relationType"] in ("essential", "optional"):
            key = (r["occupationUri"], r["skillUri"])
            # If ESCO lists a pair twice, essential wins over optional.
            if links.get(key, {}).get("relation") != "essential":
                links[key] = {"relation": r["relationType"], "importance": None}

    wanted = {skill for _, skill in links} | (digital_skill_uris if scope == "ict" else set())
    skill_rows = {
        s["conceptUri"]: {
            "source": "esco",
            "external_id": s["conceptUri"],
            "preferred_label": s["preferredLabel"],
            "alt_labels": split_labels(s["altLabels"]),
            "description": s["description"] or None,
            "skill_type": map_skill_type(s["skillType"]),
        }
        for s in skills
        if s["status"] == "released" and (scope == "all" or s["conceptUri"] in wanted)
    }
    link_rows = [
        {"occupation_uri": occ, "skill_uri": skill, **link}
        for (occ, skill), link in links.items()
        if skill in skill_rows
    ]
    return list(occ_rows.values()), list(skill_rows.values()), link_rows


async def run(zip_path: Path, scope: str) -> dict[str, int]:
    archive = zipfile.ZipFile(zip_path)
    occ_rows, skill_rows, link_rows = select_rows(
        read_csv(archive, "occupations_en.csv"),
        read_csv(archive, "skills_en.csv"),
        read_csv(archive, "occupationSkillRelations_en.csv"),
        {s["conceptUri"] for s in read_csv(archive, "digitalSkillsCollection_en.csv")},
        scope,
    )

    async with AsyncSessionLocal() as session:
        await upsert(
            session, Occupation, occ_rows, ("source", "external_id"), ("code", "title", "alt_labels", "description")
        )
        await upsert(
            session,
            Skill,
            skill_rows,
            ("source", "external_id"),
            ("preferred_label", "alt_labels", "description", "skill_type"),
        )
        occ_ids = await id_map(session, Occupation, "esco", (r["external_id"] for r in occ_rows))
        skill_ids = await id_map(session, Skill, "esco", (r["external_id"] for r in skill_rows))
        await upsert(
            session,
            OccupationSkill,
            [
                {
                    "occupation_id": occ_ids[r["occupation_uri"]],
                    "skill_id": skill_ids[r["skill_uri"]],
                    "relation": r["relation"],
                    "importance": r["importance"],
                    "source": "esco",
                }
                for r in link_rows
            ],
            ("occupation_id", "skill_id"),
            ("relation", "importance", "source"),
        )
        counts = {
            "occupations": len(occ_rows),
            "skills": len(skill_rows),
            "occupation_skills": len(link_rows),
            "essential_links": sum(1 for r in link_rows if r["relation"] == "essential"),
        }
        await record_import(session, "esco", ESCO_VERSION, scope, zip_path, counts)
        await session.commit()
    return counts


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scope", choices=("ict", "all"), default="ict")
    parser.add_argument("--file", type=Path, default=DEFAULT_ZIP, help="ESCO CSV zip (English classification)")
    args = parser.parse_args(argv)

    if not args.file.exists():
        print(f"ESCO zip not found at {args.file}. Request it from the ESCO download page (see module docstring).")
        return 1
    try:
        counts = await run(args.file, args.scope)
    finally:
        await engine.dispose()
    print(f"ESCO {ESCO_VERSION} ({args.scope}) imported: {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
