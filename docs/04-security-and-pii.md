# 04 — Security & PII Policy: SkillBridge Engine & BuildHub

| | |
|---|---|
| **Status** | Draft v0.2, aligned with [00-master-architecture.md](00-master-architecture.md) §3. **Not legal advice**; get a legal review before public launch |
| **Last updated** | 2026-11-06 |
| **Related** | [00-master-architecture.md](00-master-architecture.md) · [02-architecture.md](02-architecture.md) |

**MUST / MUST NOT / SHOULD** follow RFC 2119 meaning. Every MUST maps to a test or checklist item in §9.

---

## 1. Data classification

| Class | Examples | Rule |
|---|---|---|
| **Public** | ESCO/O*NET taxonomy, embeddings of taxonomy labels | Normal storage |
| **Internal** | Scores, skill deltas, saved roles, BuildHub projects | Owner and backend only |
| **Personal (PII)** | Email, display name, region, skill list | Minimized; never logged; SSL in transit (Neon enforces it) |
| **Sensitive PII** | **Anti-Resume** (deal-breakers, negative employer feedback), password hashes | Isolated schema, field-level encryption or one-way hashing, owner-only |
| **Transient** | **Raw résumé files and text** | Memory only; MUST NOT be persisted |

**Never collected:** date of birth, photo, gender, ethnicity, nationality, home address, government IDs. Matching doesn't need them.

---

## 2. Zero permanent résumé storage

### 2.1 Rule
Raw résumé files and their extracted text MUST NOT be written to the database, local disk, temp files, logs, error reports or analytics.

### 2.2 Flow

```mermaid
sequenceDiagram
    participant U as User
    participant API as FastAPI
    participant R as PII redactor (in memory)
    participant G as Gemini
    participant DB as Neon

    U->>API: Upload résumé (≤ 5 MB)
    Note over API: Bytes kept in RAM only
    API->>API: Extract text in memory
    API->>R: Remove emails, phones, addresses, names, personal URLs
    R-->>API: Redacted text
    API->>G: "Extract skills" (JSON schema)
    G-->>API: Skill labels
    API->>DB: Map to taxonomy and store skill IDs only (user_skills)
    API->>API: Discard bytes and text
    API-->>U: Skills found; please confirm
```

### 2.3 Implementation rules
- Reject files over **5 MB** before reading the whole body.
- FastAPI/Starlette `UploadFile` can spill large uploads to a temp file on disk. Read the stream into memory under the size limit, or raise the spool threshold above it, so nothing touches disk.
- Error handlers MUST NOT log request bodies.
- Store **only taxonomy skill IDs**, never sentences or excerpts from the résumé.

---

## 3. Anti-Resume confidentiality

### 3.1 Who can see what

| Actor | Access |
|---|---|
| The candidate (owner) | Full read/write via authenticated API |
| Scoring engine | Reads `skill_id` and `severity` only; never decrypts notes |
| Gemini / any LLM | **None.** No Anti-Resume field may appear in any prompt |
| BuildHub teammates, community feeds | **None** |
| Employers / pitch recipients | **None**; pitches are built without it |
| ETL / Airflow | **None** (no database grants on the `private` schema) |
| Analytics | Counts only, no content |

### 3.2 Controls
- Stored in a separate Postgres schema, `private`. The ETL database role has no grants on it.
- Free-text notes, such as negative employer feedback, are **encrypted** with AES-256-GCM (Python `cryptography` library) before saving. The key comes from `ANTI_RESUME_ENCRYPTION_KEY` in the environment, never from the database.
- Every query filters by the authenticated `user_id`. Add Postgres Row-Level Security as a second layer.
- Public and team response models (Pydantic) MUST NOT contain any Anti-Resume field. A test scans the OpenAPI schema to enforce this.
- Deleting an item deletes the row. Deleting the account deletes all items.

---

## 4. Authentication: stateless JWT

| Item | Rule |
|---|---|
| Access token | Signed JWT, **15-minute** expiry, sent in the `Authorization: Bearer` header |
| Refresh token | Signed JWT, 7-day expiry, in an `HttpOnly; Secure; SameSite=Strict` cookie |
| Algorithm | HS256 with `JWT_SECRET_KEY` (≥ 32 random bytes). Pin the algorithm on decode and reject `alg: none` |
| Claims | `sub` (user UUID), `exp`, `iat`, `type` (access/refresh), `ver` (token version). **No email or other PII**: JWTs are readable by anyone who has one |
| Revocation | Requests are checked statelessly. Only the **refresh** step reads `users.token_version`. Bumping it on logout-everywhere or a password change kills all sessions within 15 minutes |
| Passwords | **Argon2id** (`argon2-cffi`); bcrypt acceptable. Never plain hashes |
| Login abuse | Rate-limit login and refresh; generic "invalid credentials" errors |

---

## 5. Gemini API rules
1. **Free tier = development only.** Google's terms for unpaid Gemini API usage allow submitted content to be used to improve its products. While on the free tier, process **only synthetic résumés or your own**.
2. **Launch blocker:** switch to the paid tier before any real user uploads a résumé. Re-check Google's current terms at that time and note the date checked in this file.
3. Send **redacted** text only (§2.2). Never send Anti-Resume content, emails, phone numbers or names.
4. Don't log full prompts or responses. Log model name, token counts and latency.
5. Restrict the API key in Google AI Studio / Cloud console to the Gemini API.

---

## 6. Secrets and environment variables

### 6.1 Rules
- `.env` MUST NOT be committed. It's already in `.gitignore`. `.env.example` holds placeholders only.
- All settings load through `pydantic-settings` ([`app/core/config.py`](../app/core/config.py)). Secrets are typed `SecretStr`, so they're masked if printed or logged.
- Separate secrets per environment: Neon `dev` branch locally, `main` branch in production. Never copy production secrets to the laptop.
- In production, set secrets in the hosting platform's environment settings (Render/Fly.io, Streamlit/Vercel), never in files in the repo.
- If a secret leaks, rotate it immediately: reset the Neon role password in the Neon console, create a new Gemini key and change `JWT_SECRET_KEY`, which logs everyone out.
- Add a secret scanner (e.g., gitleaks) as a pre-commit hook once git is set up.

### 6.2 Inventory

| Variable | Secret? | Phase | Notes |
|---|---|---|---|
| `DATABASE_URL` | ✅ | 1 | Neon direct connection string for the `dev` branch |
| `ENVIRONMENT`, `DEBUG`, `DB_*` | – | 1 | `DEBUG` and `DB_ECHO` MUST be `false` in production (`DB_ECHO` logs SQL values, which can include PII) |
| `GEMINI_API_KEY` | ✅ | 1–2 | Embeddings (Phase 1), parsing and drafting (Phase 2) |
| `JWT_SECRET_KEY` | ✅ | 2 | Generate with `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `ANTI_RESUME_ENCRYPTION_KEY` | ✅ | 2 | 32 random bytes, base64. **Losing it makes notes unreadable**; keep a secure copy |

### 6.3 Local machine
- The old local PostgreSQL 12 service isn't used by this project anymore. Stopping it frees RAM and removes an unused attack surface.
- Neon requires SSL. The app enforces it for `*.neon.tech` hosts ([`app/db/url.py`](../app/db/url.py)).

---

## 7. Outreach: no automated sending
- The pitch generator only **drafts** text. There MUST be no code that sends email, LinkedIn messages or any other message, schedules sends or runs bots.
- SkillBridge stores no contact database. The candidate types who the draft is for.
- Drafts are rate-limited per user per week.
- Candidates are responsible for sending lawfully. The UI reminds them to send only to professional contacts and to respect opt-outs.

---

## 8. Logging and retention

| Data | Retention |
|---|---|
| Raw résumé | **Never stored** |
| Skills, saved roles, scores | Life of the account |
| Anti-Resume | Until the user deletes it or the account |
| Logs | 30 days, with no PII, résumé text, Anti-Resume content, tokens or keys |

Users can export their data (JSON) and delete their account from day one of Phase 2.

---

## 9. Verification checklist

| # | Check | How |
|---|---|---|
| S1 | Résumé never persisted | Upload a test file containing a unique marker string; assert the marker is absent from all tables, temp folders and logs |
| S2 | Anti-Resume never exposed | OpenAPI schema scan; cross-user request returns 404; ETL role can't read `private` |
| S3 | Anti-Resume never sent to Gemini | Unit test of every prompt builder with marker strings |
| S4 | JWT hardening | `alg:none`, expired tokens and old `ver` are all rejected |
| S5 | No secrets in the repo | gitleaks in pre-commit |
| S6 | Production config safe | On startup with `ENVIRONMENT=production`, refuse to run if `DEBUG` or `DB_ECHO` is true |
| S7 | No automated outbound | Code review plus a test that no email/HTTP-sending client is imported by the pitch module |
| S8 | Free-tier rule | Release checklist: Gemini tier confirmed paid before real résumés |
