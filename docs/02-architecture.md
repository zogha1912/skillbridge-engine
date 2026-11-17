# 02 — Architecture: SkillBridge Engine & BuildHub

| | |
|---|---|
| **Status** | Draft v0.2, aligned with [00-master-architecture.md](00-master-architecture.md) |
| **Last updated** | 2026-11-06 |
| **Related** | [00-master-architecture.md](00-master-architecture.md) · [04-security-and-pii.md](04-security-and-pii.md) |

---

## 1. System overview

```mermaid
flowchart LR
    subgraph Laptop["Developer laptop (8 GB RAM)"]
        API["FastAPI (async)<br/>.venv"]
        AF["Airflow venv<br/>inside WSL2<br/>(run only for ETL)"]
    end

    subgraph Cloud
        NEON[("Neon PostgreSQL<br/>+ pgvector")]
        GEM[["Gemini API<br/>google-genai SDK"]]
        ESCO[ESCO bulk data / API]
        ONET[O*NET bulk data / API]
    end

    UI["UI<br/>Vercel or Streamlit Cloud"] --> API
    API <-->|SSL| NEON
    API -->|redacted text only| GEM
    AF --> ESCO
    AF --> ONET
    AF -->|embeddings| GEM
    AF -->|upsert taxonomy| NEON
```

**Design principles**
1. **Nothing heavy runs locally.** The database lives on Neon, and all language processing goes to Gemini. The laptop runs only the API and, when needed, Airflow.
2. **The LLM extracts and drafts; Python decides.** Scores are computed by deterministic, tested Python code (§4), never by the LLM.
3. **Async end to end:** FastAPI, SQLAlchemy 2.x async, asyncpg.
4. **Privacy by construction:** résumés stay in memory only, and the Anti-Resume is isolated and encrypted (doc 04).

---

## 2. Technology stack

| Layer | Choice | Status / notes |
|---|---|---|
| API | FastAPI + Uvicorn, Pydantic v2 | ✅ `app/main.py` with `/health` |
| ORM | SQLAlchemy 2.x async + asyncpg | ✅ `app/db/database.py` |
| Config | pydantic-settings + `.env` | ✅ `app/core/config.py`; secrets typed as `SecretStr` |
| Database | **Neon** PostgreSQL + pgvector | ✅ code ready; ⏳ waiting for the Neon connection string |
| Migrations | Alembic (async) | ✅ `migrations/`, first revision `0001` |
| ETL | Apache Airflow in a venv **inside WSL2**, SQLite metadata DB | ⏳ Phase 1 |
| LLM | Gemini API via `google-genai` (free tier during development) | ⏳ Phase 2; free-tier data rule in doc 04 §5 |
| Taxonomies | ESCO + O*NET | ⏳ Phase 1 ETL |
| Hosting | Neon (DB), Render/Fly.io (API), Vercel or Streamlit Community Cloud (UI) | ⏳ after Phase 2 |
| Tests | pytest | ✅ `tests/test_db_url.py` |

### 2.1 Why Neon for development, not Docker
- **Zero local RAM.** A Docker Desktop install on Windows runs its own WSL2 VM on top of the database container. On an 8 GB machine that competes with the browser, VS Code and Airflow.
- **pgvector is built in.** Run `CREATE EXTENSION vector` (migration `0001` does it).
- **Same engine as production.** Use Neon **branches** to get separate `dev` and `main` (production) databases from one project.
- **Scales to zero.** The compute sleeps when idle. The first request after a pause takes a moment longer, and `pool_pre_ping=True` handles connections dropped while it slept.
- **Trade-off:** you need internet to develop.

### 2.2 How the app connects to Neon
Neon gives a libpq-style URL such as `postgresql://user:pass@ep-xxx.region.aws.neon.tech/neondb?sslmode=require&channel_binding=require`. asyncpg can't read `sslmode` or `channel_binding`, so [`app/db/url.py`](../app/db/url.py) does three things:
1. switches the driver to `postgresql+asyncpg`;
2. moves `sslmode` into `connect_args={"ssl": ...}` and always requires SSL for `*.neon.tech`;
3. if the host is a **pooled** endpoint (`-pooler` in the name), turns off prepared-statement caching, which PgBouncer transaction pooling can't support.

**Two connection strings, both written by `neon env pull` / `neon checkout`:**

| Variable | Endpoint | Used by |
|---|---|---|
| `DATABASE_URL` | Pooled (`-pooler`) | The FastAPI app ([`app/db/database.py`](../app/db/database.py)) |
| `DATABASE_URL_UNPOOLED` | Direct | Alembic migrations ([`migrations/env.py`](../migrations/env.py)), dumps, anything needing session state |

The pooler runs PgBouncer in transaction mode, so session state does not survive between transactions. Consequence for the Anti-Resume Row-Level Security plan (doc 04 §3.2): set the user ID with `SET LOCAL` (or `set_config(..., true)`) **inside** each transaction, never a plain `SET`.

### 2.3 Neon project layout
- Project `misty-glade-31147298` (AWS us-east-1), linked through the git-ignored `.neon` file.
- Branch `production` (default) for the deployed app; branch `dev` for local work. `neon checkout dev` switches `.env` to it.
- [`neon.ts`](../neon.ts) declares the Neon services (Postgres only for now). `neon config plan` previews changes; `neon deploy` applies them. `package.json` exists only to hold `neon.ts`'s dependencies.
- Verify the setup at any time: `python -m scripts.check_db` and `python -m scripts.smoke_test_db`.

---

## 3. Data model

### 3.1 Entity-relationship diagram

```mermaid
erDiagram
    OCCUPATIONS ||--o{ OCCUPATION_SKILLS : requires
    SKILLS ||--o{ OCCUPATION_SKILLS : "required by"
    USERS ||--o{ USER_SKILLS : has
    SKILLS ||--o{ USER_SKILLS : ""
    USERS ||--o{ ANTI_RESUME_ITEMS : "privately lists"
    SKILLS |o--o{ ANTI_RESUME_ITEMS : "points at"
    USERS ||--o{ TARGET_ROLES : saves
    OCCUPATIONS ||--o{ TARGET_ROLES : ""
    TARGET_ROLES ||--o{ SCORE_SNAPSHOTS : "scored as"
    BUILDHUB_PROJECTS ||--o{ PROJECT_SKILLS : targets
    SKILLS ||--o{ PROJECT_SKILLS : ""
    BUILDHUB_PROJECTS ||--o{ TEAM_MEMBERS : has
    USERS ||--o{ TEAM_MEMBERS : joins
    BUILDHUB_PROJECTS ||--o{ PROOF_ARTIFACTS : produces
    USERS ||--o{ PROOF_ARTIFACTS : owns
    USERS ||--o{ PITCH_DRAFTS : drafts
    TARGET_ROLES ||--o{ PITCH_DRAFTS : "for"
```

### 3.2 Tables

| Table | Key columns | Phase | Notes |
|---|---|---|---|
| `skills` | `id`, `source ∈ {esco, onet}`, `external_id` (UNIQUE with source), `preferred_label`, `alt_labels TEXT[]`, `description`, `skill_type ∈ {skill, knowledge, technology, …}`, `embedding VECTOR(768)` | ✅ 1 | `external_id`: ESCO URI, O*NET element ID, or `tech:<name>` for O*NET technology examples |
| `occupations` | `id`, `source`, `external_id` (UNIQUE with source), `code`, `title`, `alt_labels TEXT[]`, `description`, `embedding VECTOR(768)` | ✅ 1 | Standardized role profiles ($S_{\text{target}}$); one row per source because ESCO ↔ O*NET is many-to-many |
| `occupation_skills` | `occupation_id`, `skill_id` (PK), `relation ∈ {essential, optional}`, `importance ∈ [0,1]`, `source ∈ {esco, onet}` | ✅ 1 | Gives skill weights $w_k$ (§4.2) |
| `occupation_crosswalk` | `onet_soc_code`, `esco_uri` (PK), `match_type` (`exactMatch`, `closeMatch`, `broadMatch`, …) | ✅ 1 | Official ESCO–O*NET mapping, keyed by external IDs |
| `taxonomy_imports` | `source`, `version`, `scope`, `file_sha256`, `row_counts JSONB`, `imported_at` | ✅ 1 | Provenance of every import (attribution + reproducibility) |
| `users` | `id UUID`, `email UNIQUE`, `password_hash`, `token_version`, `created_at` | 2 | |
| `user_skills` | `user_id`, `skill_id`, `source ∈ {resume, manual, buildhub}`, `confirmed BOOL` | 2 | $S_{\text{user}}$; only skill IDs, never résumé text |
| `anti_resume_items` *(schema `private`)* | `id`, `user_id`, `skill_id NULL`, `severity ∈ {hard, strong, mild}`, `note_ciphertext BYTEA NULL` | 2 | $A_{\text{user}}$; encrypted note; see doc 04 §3 |
| `target_roles` | `user_id`, `occupation_id`, `saved_at` | 2 | The user's roadmap |
| `score_snapshots` | `user_id`, `occupation_id`, `match`, `penalty`, `final_score`, `pruned`, `delta JSONB`, `engine_version`, `created_at` | 2 | Immutable. `delta` holds skill IDs only |
| `buildhub_projects`, `project_skills`, `team_members` | | 3 | |
| `proof_artifacts` | `user_id`, `project_id NULL`, `url`, `kind` | 3 | Links to repos and demos |
| `pitch_drafts` | `user_id`, `occupation_id`, `recipient_label`, `draft_text`, `status ∈ {draft, copied, discarded}` | 4 | Recipient typed by the user; no contact database |

### 3.3 Embedding size
Gemini embeddings are requested at **768 dimensions** (`EMBEDDING_DIM` in [`app/models/taxonomy.py`](../app/models/taxonomy.py)). That's well under pgvector's 2,000-dimension HNSW index limit, and small enough that the ESCO and O*NET taxonomies fit in Neon's free storage. Changing the size needs a new migration and re-embedding everything.

---

## 4. Mathematical engine

✅ Implemented in [`app/services/engine/scoring.py`](../app/services/engine/scoring.py) as pure Python functions with no database or network calls: `score_role(target, user_skills, anti_resume, similarity, config)` returns Match, the ranked Δ, overlaps, penalty, Final Score and the pruning flag. Similarity is passed in as a function, so the app can back it with pgvector and tests with a table. A role with no skills scores 0 and is pruned. Tests: [`tests/test_scoring_engine.py`](../tests/test_scoring_engine.py) (worked example below, edge cases, 200 randomized property checks).

### 4.1 Inputs

| Symbol | Meaning | Source |
|---|---|---|
| $S_{\text{target}}$ | Skills of the target occupation | `occupation_skills` |
| $w_k \in (0, 1]$ | Weight of skill $k$ in the target | O*NET `importance` if present, else essential = 1.0, optional = 0.5 |
| $S_{\text{user}}$ | Candidate's confirmed skills | `user_skills` (from résumé parsing plus user confirmation) |
| $A_{\text{user}}$ | Anti-Resume items | `anti_resume_items` |
| $\sigma_a$ | Severity of item $a$ | hard = 1.0, strong = 0.5, mild = 0.2 |
| $\text{sim}(x, y)$ | Cosine similarity of two skill embeddings | pgvector (`1 - (a <=> b)`) |

### 4.2 Skill Delta

A target skill $k$ is **covered** if the user has it, or has a skill that is near-identical by embedding:

$$\text{covered}(k) \iff k \in S_{\text{user}} \ \lor\ \max_{u \in S_{\text{user}}} \text{sim}(u, k) \ge \tau_m \qquad (\tau_m = 0.90)$$

$$\Delta_{\text{skills}} = \{\, k \in S_{\text{target}} : \lnot\,\text{covered}(k) \,\}$$

The delta is returned **sorted by $w_k$, highest first**, with essential skills first. That ordering is the learning roadmap.

### 4.3 Match

$$\text{Match}(S_{\text{user}}, S_{\text{target}}) = \frac{\sum_{k \in S_{\text{target}},\ \text{covered}(k)} w_k}{\sum_{k \in S_{\text{target}}} w_k} \in [0, 1]$$

### 4.4 Overlap with the Anti-Resume

For each Anti-Resume item $a$ (linked to taxonomy skill $s_a$), find the target skill it resembles most:

$$\text{Overlap}(a, \text{Tasks}_{\text{target}}) =
\begin{cases}
\sigma_a \cdot w_{t^*} \cdot \text{sim}(s_a, t^*) & \text{if } \text{sim}(s_a, t^*) \ge \tau_o \\
0 & \text{otherwise}
\end{cases}
\qquad t^* = \arg\max_{t \in S_{\text{target}}} \text{sim}(s_a, t)$$

with $\tau_o = 0.80$. Matching uses the **taxonomy skill's embedding**, which is public data already in the database. The user's private note is never embedded or sent to Gemini.

### 4.5 Final score and pruning

$$\text{Final Score} = \text{Match} - \alpha \sum_{a \in A_{\text{user}}} \text{Overlap}(a, \text{Tasks}_{\text{target}}) \qquad (\alpha = 1.5)$$

**Pruning rule:** a role is removed from the roadmap when $\text{Final Score} \le 0$.

This rule has a useful consequence. A **hard** deal-breaker that matches an **essential** skill gives $\text{Overlap} \ge 1.0 \cdot 1.0 \cdot 0.80 = 0.80$, so the penalty is $\ge 1.2$. Since Match is at most 1, that role is always pruned, without any special-case code.

### 4.6 Worked example

The candidate has {Python, SQL, Docker}. Their Anti-Resume holds: *COBOL* (hard) and *on-call incident response* (strong).

**Role A: Backend Developer**

| Skill | Relation | $w$ | Covered? |
|---|---|---|---|
| Python | essential | 1.0 | ✅ |
| SQL | essential | 1.0 | ✅ |
| REST API design | essential | 1.0 | ❌ |
| Docker | optional | 0.5 | ✅ |
| On-call incident response | optional | 0.5 | ❌ |

- Match = (1 + 1 + 0.5) / 4.0 = **0.625**
- Δ = [REST API design (1.0), on-call incident response (0.5)]
- Overlap(on-call) = 0.5 × 0.5 × 0.95 = 0.2375; Overlap(COBOL) = 0, because no similar skill is present
- Final = 0.625 − 1.5 × 0.2375 = **0.269**, so the role is **kept** (ranked lower)

**Role B: Mainframe Application Developer** (COBOL, SQL and JCL, all essential)

- Match = 1 / 3 = 0.333
- Overlap(COBOL) = 1.0 × 1.0 × 1.0 = 1.0
- Final = 0.333 − 1.5 = **−1.167**, so the role is **pruned**

### 4.7 Configuration and testing
- $\alpha$, $\tau_m$, $\tau_o$, the severity weights and the essential/optional default weights are settings, versioned by `engine_version` in every `score_snapshots` row.
- Required tests: the worked example above as a fixed-answer test; Match always between 0 and 1; adding a user skill never lowers Match; adding an Anti-Resume item never raises Final Score.

---

## 5. Gemini integration (`google-genai`)

| Use | Input sent | Output stored |
|---|---|---|
| Résumé parsing | Résumé text **after PII redaction**, in memory | Skill labels, mapped to taxonomy IDs → `user_skills` |
| Taxonomy embeddings | Public skill and occupation labels and descriptions | `skills.embedding`, `occupations.embedding` |
| Mapping free-text skills | A skill label (e.g., "FastAPI") | Nearest taxonomy skill via pgvector |
| Pitch drafting | Role title, the user's public project links, user's own short notes | `pitch_drafts.draft_text` |

**Never sent:** Anti-Resume content, emails, phone numbers, names or raw unredacted résumés.

**Free-tier handling:** use structured JSON output with a schema; retry with exponential backoff on rate-limit errors; batch embedding requests; cache by content hash so the same text is never embedded twice. Model names live in settings.

---

## 6. ETL with Airflow

### 6.0 Decision (2026-11-17): Airflow deferred, lightweight pipeline runner instead
Measured on the development laptop: 7.9 GB RAM with only ~1.4 GB free during normal work, 1.5 GB already compressed and 1.6 GB in the pagefile. WSL2 plus the Airflow scheduler and web UI would need roughly 2–3 GB, which would push the machine into heavy swapping. Airflow would add little: every step is idempotent and logged in `taxonomy_imports`.

Instead:
- **`python -m etl.pipeline`** runs ESCO → O*NET → crosswalk → embeddings in order and stops at the first failure (`--only`, `--skip`, `--scope`). Exit code 2 means the Gemini daily quota stopped the embeddings; re-run after the reset.
- **`scripts/daily_embed.cmd`** runs the embedding step and appends to `data/logs/embed.log`. It's meant for a daily Windows scheduled task while the free-tier quota (1,000 texts/day) limits embedding.

Revisit Airflow (or a managed scheduler) when the pipeline runs on a server instead of this laptop. The notes below apply then.

### 6.1 Running Airflow on an 8 GB Windows laptop
- Airflow does **not** support native Windows. Install it in a Python venv **inside WSL2 (Ubuntu)**. That's still a plain venv, with no Docker.
- Cap WSL2's memory in `%UserProfile%\.wslconfig`, for example `[wsl2]` then `memory=3GB`.
- Use `airflow standalone` with the default **SQLite** metadata database. Which executor works with SQLite depends on the Airflow version: Airflow 2 allows only the SequentialExecutor. Check the docs for the version you install. Don't point Airflow's own metadata at Neon, because it would use up free-tier compute hours.
- **Start Airflow only for an ETL run, then stop it.** The taxonomy changes rarely, so there's no need to keep it running.

### 6.2 Pipeline
Each task is a plain Python module in `etl/`, so it can run **without Airflow** (`python -m etl.esco_import`). The DAG just calls these modules in order.

```mermaid
flowchart LR
    D1[Download ESCO bulk CSV] --> L1[Load skills + occupations + relations]
    D2[Download O*NET database files] --> L2[Load importance ratings + SOC codes]
    L1 --> X[Cross-link ESCO ↔ O*NET occupations]
    L2 --> X
    X --> E[Embed new or changed labels via Gemini]
    E --> U[Upsert into Neon]
```

| Task | Detail |
|---|---|
| ESCO import | ✅ `python -m etl.esco_import [--scope ict\|all]`. Bulk CSV v1.2.1 (English), requested by email from the ESCO portal and saved as `data/raw/esco/esco_v1.2.1_en_csv.zip`. Uses `occupations_en`, `skills_en` (with `altLabels`), `occupationSkillRelations_en` (essential/optional) and `digitalSkillsCollection_en`. ICT scope = ISCO `25*`, `351*`, `1330` plus all digital skills |
| O*NET import | ✅ `python -m etl.onet_import [--scope ict\|all]`. O*NET 31.0 text zip (downloaded automatically). Uses `Occupation Data`, `Knowledge`, `Essential Skills`, `Transferable Skills` (importance scale `IM`, 1–5 rescaled to 0..1; rows below 2.5, suppressed or "not relevant" dropped; ≥ 3.5 = essential) and `Software Skills` (technology examples, linked as optional). ICT scope = SOC `15-*`, `11-3021`, `17-2061` |
| Cross-link | ✅ `python -m etl.crosswalk_import`. Official ESCO–O*NET occupation crosswalk (ESCO Secretariat + USDOL/ETA, v1, Sep 2022); rows pointing at ISCO groups are skipped |
| Embed | Only rows whose text hash changed; batched; 768 dimensions |
| Upsert | `INSERT ... ON CONFLICT (esco_uri / onet_element_id) DO UPDATE` |

Attribution for ESCO and O*NET is shown in the UI footer and the API docs. Required O*NET wording: *"This page includes information from the O*NET 31.0 Database by the U.S. Department of Labor, Employment and Training Administration (USDOL/ETA). Used under the CC BY 4.0 license. O*NET® is a trademark of USDOL/ETA."* Because the importer filters and rescales the data, also add: *"SkillBridge has modified all or some of this information. USDOL/ETA has not approved, endorsed, or tested these modifications."*

ESCO is reusable for any purpose under Commission Decision 2011/833/EU. Required wording: *"This service uses the ESCO classification of the European Commission."* (linked to https://ec.europa.eu/esco), and *"Any modified or adapted version of ESCO must be clearly indicated as such"*, so also state that the data is filtered and restructured. Do not use EU logos or imply EU endorsement.

Importers are idempotent (upserts on `(source, external_id)`), so re-running them is safe; each run adds a `taxonomy_imports` row.

---

## 7. Repository layout

```
skillbridge-engine/
├── app/
│   ├── main.py              ✅ FastAPI app + /health
│   ├── core/config.py       ✅ settings from .env
│   ├── db/                  ✅ base.py, database.py (engine/session), url.py (Neon → asyncpg)
│   ├── models/              ✅ taxonomy.py (skills, occupations, occupation_skills)
│   ├── schemas/             ⏳ Pydantic request/response models
│   ├── api/v1/              ⏳ routers
│   └── services/            ⏳ engine/ (math), llm/ (Gemini), resume/ (in-memory parsing)
├── etl/                     ⏳ esco_import.py, onet_import.py, embed.py
├── airflow/dags/            ⏳ taxonomy_etl.py (calls etl/*)
├── migrations/              ✅ Alembic (0001_taxonomy_tables)
├── scripts/check_db.py      ✅ connection + pgvector check
├── tests/                   ✅ test_db_url.py
└── docs/
```
