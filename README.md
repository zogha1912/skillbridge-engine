# SkillBridge Engine

A privacy-first career positioning platform for people moving into modern tech roles.

Instead of matching keywords, SkillBridge compares a candidate's skills with **standardized role profiles** (ESCO and O*NET) and shows the exact gap, the **Skill Delta**. Candidates can also keep a private **Anti-Resume**: tasks, workflows and technologies they refuse to work on. Roles that clash with it are ranked down or removed from their roadmap.

> 🚧 **Status: early development (Phase 1, infrastructure).** The API skeleton, database layer and first schema are in place. Taxonomy import is next.

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
- **Data pipeline:** Apache Airflow (planned)
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

This project uses the ESCO classification of the European Commission and the O*NET database of the US Department of Labor. Attribution will be shown in the app once taxonomy data is imported.
