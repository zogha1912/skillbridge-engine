# SkillBridge Engine & BuildHub — Master System Architecture

> **This is the source of truth.** Documents 01–04 expand on it and must not contradict it. If they disagree, this file wins, and the other document gets fixed.

## 1. System Architecture Overview
SkillBridge Engine is a lightweight, secure, and privacy-focused career positioning platform designed to help job-seekers transition into modern tech roles by bypassing traditional application black holes.

### Core Stack Components
* **Backend Framework:** FastAPI (Python 3.11+) operating strictly with asynchronous endpoints (`async/await`) and Pydantic v2 schemas for data validation.
* **Database & Vector Index:** PostgreSQL paired with the `pgvector` extension for semantic skill embeddings and vector matching, hosted on **Neon.tech for both development and production** (separate Neon branches per environment).
* **Orchestration & Data Pipeline:** Apache Airflow running locally in a Python Virtual Environment (`venv`) **inside WSL2** (Airflow does not support native Windows) with a SQLite metadata database for lightweight background ETL processing.
* **Artificial Intelligence Layer:** Google Gemini API (Free Tier via `google-genai` SDK) used exclusively for structured JSON extraction, resume parsing, and cold outreach script drafting. *See the free-tier data rule in §3.*
* **Deployment Target:** Decoupled architecture deploying database to Neon.tech, API backend to Render/Fly.io, and frontend UI to Vercel (React/Next.js UI) or Streamlit Community Cloud (Streamlit UI).

---

## 2. Core Concepts & Mathematical Engine

### Skill Delta Analysis ($\Delta_{\text{skills}}$)
Traditional matching engines evaluate static keyword overlaps. SkillBridge evaluates the exact capability deficit between a candidate's current profile ($S_{\text{user}}$) and a standardized target role profile ($S_{\text{target}}$):

$$\Delta_{\text{skills}} = S_{\text{target}} \setminus S_{\text{user}}$$

### Anti-Resume Penalty Matrix
Candidates specify their **Anti-Resume** ($A_{\text{user}}$)—a list of deal-breaker tasks, toxic workflows, or legacy technologies they refuse to work on.

When evaluating a target career path or job profile, the engine applies a negative penalty weight to paths containing high clusters of these anti-skills:

$$\text{Final Score} = \text{Match}(S_{\text{user}}, S_{\text{target}}) - \left( \sum \text{Overlap}(A_{\text{user}}, \text{Tasks}_{\text{target}}) \times \alpha \right)$$

*Where $\alpha$ is a configurable penalty multiplier (default: $1.5$). Paths with excessive overlap are pruned from user roadmaps.* Exact definitions of Match, Overlap and the pruning rule are in [02-architecture.md §4](02-architecture.md#4-mathematical-engine).

---

## 3. System Operational Constraints

### Local Environment Limits (8GB RAM Optimization)
* **No Heavy Docker Clusters:** Apache Airflow MUST NOT be run using official Docker Compose stacks locally due to memory bloat (4GB+ RAM consumption). Airflow is executed directly in a Python `venv` inside WSL2, and only while an ETL run is needed.
* **No Local Database Server:** The database runs on Neon.tech, so it uses no local RAM. *(Optional offline fallback only: a single capped container using the pgvector image and an env file, never an inline password:*
  `docker run --name skillbridge-db --env-file .env.docker -p 5432:5432 -m 512m --cpus=1.0 -d pgvector/pgvector:pg17`*)*
* **Offloaded LLM Processing:** No local heavy LLM models or local vectorizers are executed on CPU/RAM. All natural language processing is offloaded to the cloud via the Gemini API.

### Security, Confidentiality & PII Protection Standards
1. **Zero Permanent Resume Storage:** Raw user resume text and uploaded files MUST NOT be stored permanently on local disks or database blobs. Resumes are parsed in memory, converted into structured JSON skill vectors, and raw text is immediately purged.
2. **Anti-Resume Confidentiality:** Anti-resume preferences (e.g., negative employer feedback, deal-breaker tasks) are treated as Sensitive Personally Identifiable Information (PII). They are strictly private to the candidate and must NEVER be exposed in public team-matching views or community feeds, and never sent to the LLM.
3. **Stateless Credential Management:** All sensitive tokens (Gemini API keys, PostgreSQL credentials, JWT secret keys) are managed strictly via environment variables using `.env` and `pydantic-settings`. No hardcoded keys are permitted.
4. **Secure Session Handling:** User authentication utilizes cryptographically signed stateless JSON Web Tokens (JWT) with short expiration windows and Bcrypt/Argon2 password hashing.
5. **No Automated Spam Outbound:** Cold pitch generators MUST only produce drafted text templates for manual candidate review. The system strictly prohibits automated mass-outreach scripts or automated messaging bot executions.
6. **Gemini Free-Tier Data Rule:** Google's terms for the unpaid Gemini API allow submitted content to be used to improve its products. While on the free tier, only **synthetic or the developer's own** résumés may be processed, and PII is redacted before any call. Moving to the paid tier is a **blocker before real users upload résumés**.

---

## 4. Primary External Taxonomies & Data Sources
* **ESCO API (European Commission):** Free multilingual classification mapping 13,000+ skills and 3,000+ occupations.
* **O*NET API (US Department of Labor):** Free standardized occupational taxonomy providing skill importance ratings and career outlooks.

Both also publish **bulk downloads**, which the ETL prefers over per-item API calls. Both require attribution; confirm each licence before production use.

---

### Changes from the original draft (2026-11-06)
| Change | Reason |
|---|---|
| Database moved from a local Docker container to Neon.tech for development too | Saves RAM on the 8 GB laptop; Neon includes pgvector and matches production |
| Docker fallback uses `pgvector/pgvector:pg17` and `--env-file` | The plain `postgres` image has no pgvector; the inline `POSTGRES_PASSWORD=mysecret` broke rule §3.3 |
| Airflow runs in a venv **inside WSL2** | Airflow does not support native Windows |
| "SQLite / LocalExecutor" changed to "SQLite metadata database" | The executors allowed with SQLite depend on the Airflow version; see 02-architecture §6 |
| Added §3 rule 6 (Gemini free tier) | Free-tier data terms conflict with rule 1 for real users |
| Rule 2: "never sent to the LLM" | Keeps Anti-Resume content out of third-party processing |
| Streamlit UI hosted on Streamlit Community Cloud | Vercel hosts JS frontends; it doesn't run Streamlit apps |
| Typo "Personably" → "Personally" | |
| 2026-11-17: Airflow deferred; `python -m etl.pipeline` runs the ETL steps instead | Measured only ~1.4 GB free RAM; WSL2 + Airflow needs ~2–3 GB. Revisit when the pipeline moves to a server (see 02-architecture §6.0) |
