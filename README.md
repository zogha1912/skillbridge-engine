# SkillBridge Engine

A privacy-first career positioning platform for people moving into modern tech roles.

Instead of matching keywords, SkillBridge compares a candidate's skills with **standardized role profiles** (ESCO and O*NET) and shows the exact gap, the **Skill Delta**. Candidates can also keep a private **Anti-Resume**: tasks, workflows and technologies they refuse to work on. Roles that clash with it are ranked down or removed from their roadmap.

> 🚧 **Status: early development (Phase 1, taxonomy import).** API skeleton, database layer and schema are in place. ESCO v1.2.1, O*NET 31.0 and the official ESCO–O*NET crosswalk are imported (ICT roles). Embeddings are next.

## Core ideas

| Concept | What it does |
|---|---|
| **Skill Delta** | $\Delta = S_{\text{target}} \setminus S_{\text{user}}$: the missing skills for a target role, ranked by importance |
| **Anti-Resume** | Private deal-breakers that apply a penalty: $\text{Final} = \text{Match} - \alpha \sum \text{Overlap}$, with $\alpha = 1.5$ |
| **BuildHub** | Small teams with complementary skills build projects that close their gaps |
| **Pitch drafts** | Outreach drafts for the candidate to review and send themselves. Nothing is ever sent automatically |

Full details: [docs/00-master-architecture.md](docs/00-master-architecture.md) and [docs/02-architecture.md](docs/02-architecture.md).

## Tech stack

- **API:** FastAPI (async) with Pydantic v2
- **Database:** PostgreSQL with pgvector on [Neon](https://neon.com); SQLAlchemy 2 (async) + asyncpg; Alembic migrations
- **AI:** Google Gemini API for structured extraction and embeddings
- **Data pipeline:** idempotent import scripts run by `python -m etl.pipeline` (Airflow deferred; see docs)
- **Taxonomies:** ESCO (European Commission) and O*NET (US Department of Labor)

## Privacy by design

- Résumés are processed in memory and **never stored**. Only standardized skill IDs are kept.
- Anti-Resume data is private to its owner, encrypted at rest, and never sent to an LLM.
- Database connections use TLS with full certificate verification.

See [docs/04-security-and-pii.md](docs/04-security-and-pii.md).

## Running locally

Requirements: Python 3.11+ and a Neon (or any PostgreSQL 15+ with pgvector) database.

```bash
python -m venv .venv
# Windows: .\.venv\Scripts\Activate.ps1   macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt

cp .env.example .env          # then fill in DATABASE_URL and DATABASE_URL_UNPOOLED

python -m scripts.check_db    # connection + pgvector check
alembic upgrade head          # create the schema
python -m scripts.smoke_test_db
python -m etl.esco_import       # ESCO v1.2.1 CSV zip, requested from the ESCO download page
python -m etl.onet_import       # O*NET 31.0, ICT roles (add --scope all for every role)
python -m etl.crosswalk_import  # official ESCO <-> O*NET occupation mapping
python -m etl.pipeline         # or run all import + embedding steps in order
pytest

uvicorn app.main:app --reload # http://127.0.0.1:8000/health and /docs
```

## Project layout

```
app/          FastAPI app, settings, database layer, ORM models
migrations/   Alembic migrations
scripts/      Database check and smoke test
tests/        Unit tests
docs/         Architecture and security documentation
```

## Data sources

This project includes information from the **O*NET 31.0 Database** by the U.S. Department of Labor, Employment and Training Administration (USDOL/ETA). Used under the [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) license. O*NET® is a trademark of USDOL/ETA. SkillBridge has modified all or some of this information. USDOL/ETA has not approved, endorsed, or tested these modifications.

This service uses the [ESCO classification](https://ec.europa.eu/esco) of the European Commission. The ESCO data used here is a modified version: it is filtered (ICT roles by default) and restructured. It also uses the official ESCO–O*NET occupation crosswalk.

The source data is downloaded by the import scripts and is not stored in this repository.
