# LLM Wiki Tab — Operator Help (Detailed)

Last updated: 2026-05-02
Scope: `custom-web-ui` LLM Wikis tab in the current build.

---

## 1) What this tab does today

The LLM Wiki tab currently supports:

1. **Wiki tile management**
   - Create/update wiki tiles with status/health/notes/last-indexed timestamp.
2. **Karpathy-style wiki bootstrap** via Wizard
   - Define subject, scope, out-of-scope, tags, seeds, sources.
   - Validate readiness before initialization.
   - Initialize wiki folder + starter files.
3. **Charter Notes management** (formerly setup interview)
   - Load/edit/save `setup-interview.md` (now used as Charter & Intake Notes).
4. **Operational metadata checks** on each tile
   - Path exists/missing
   - Charter exists/missing
   - Fresh/aging/stale index age classification

---

## 2) Karpathy-method compliance status

### Implemented now

- Schema-first bootstrap with explicit:
  - domain scope
  - out-of-scope
  - tag taxonomy
  - page conventions
  - page thresholds
- Required seed capture for:
  - entities
  - concepts
  - sources
- Standard folder scaffold:
  - `raw/articles`, `raw/papers`, `raw/transcripts`, `raw/assets`
  - `entities`, `concepts`, `comparisons`, `queries`
- Starter files:
  - `SCHEMA.md`
  - `index.md`
  - `log.md`
  - `setup-interview.md` (charter notes format)

### Not yet implemented (important)

- No deep validator that audits an **existing** wiki against all Karpathy constraints (e.g., frontmatter completeness per page, min outbound links, schema drift, orphan pages).
- No automated schema drift checker between `SCHEMA.md` and page corpus.
- No lint engine that produces pass/fail with remediation suggestions.

---

## 3) Is there a method to maintain/update `SCHEMA.md`?

### Current method

- `SCHEMA.md` is generated during wizard initialization from blueprint inputs.
- Ongoing schema decisions are intended to be tracked in **Charter Notes** (`setup-interview.md`).

### Current gap

- There is no dedicated `PATCH /schema` endpoint or UI control that safely edits `SCHEMA.md` with validation.

### Recommended interim process

1. Update Charter Notes first (rationale + desired schema change).
2. Manually edit `SCHEMA.md` in vault/editor.
3. Add a `log.md` entry describing what changed and why.
4. Re-run planned lint once implemented.

---

## 4) Adding files/links/sources into `raw/`

### Current state

- Folder structure is created automatically at init.
- There is no completed source-ingestion pipeline in the UI yet.

### What the buttons do currently

- **Ingest Source** → placeholder status message only.
- **Ask Wiki** → placeholder status message only.
- **Lint Health** → placeholder status message only.

No file import/crawl/parse/write is executed yet from those buttons.

---

## 5) Discussion/comment with LLM at ingestion time

### Current state

- Not implemented yet in this tab.
- There is no interactive ingest review loop (e.g., annotate chunks, approve mappings, reject source, discuss extraction decisions).

### Target behavior (recommended)

Add an ingestion review modal that supports:
- source preview
- extraction summary
- proposed tags/entities/concepts
- user comments and approve/reject actions
- final write to `raw/*` + `log.md`

---

## 6) Button behavior reference (current)

On each wiki tile:

- **Load to Editor**
  - Loads tile metadata into top editor.
- **Open Charter**
  - Loads charter notes for selected wiki from `setup-interview.md`.
- **Mark Indexed Now**
  - Updates `last_indexed_at` to now.
- **Ingest Source**
  - Placeholder: queues text status only.
- **Ask Wiki**
  - Placeholder: queues text status only.
- **Lint Health**
  - Placeholder: queues text status only.

Wizard controls:
- **Open 6-Step Wizard** opens modal.
- **Prev/Next Step** navigates wizard step label/focus.
- **Validate Blueprint** calls readiness validation endpoint.
- **Initialize Wiki** creates folder + starter files + tile record.
- **Reset Wizard** clears wizard fields.
- **Esc** closes modal; tab focus is trapped while modal open.

---

## 7) Practical operator workflow (today)

1. Open LLM Wikis tab.
2. Click **Open 6-Step Wizard**.
3. Fill scope/taxonomy/seeds/sources.
4. Click **Validate Blueprint**.
5. Click **Initialize Wiki**.
6. Open **Charter Notes** and refine post-init operating decisions.
7. Use external/manual ingestion until ingest/query/lint pipeline is implemented.
8. Keep `log.md` updated for governance.

---

## 8) Implementation roadmap to make this “best-in-class”

Priority 1 (high value)
1. Real ingest pipeline (URL/file -> normalized artifact -> `raw/*` write).
2. Ask Wiki retrieval pipeline over indexed content.
3. Lint Health engine:
   - frontmatter checks
   - link graph checks
   - schema conformance
   - stale/orphan detection.

Priority 2
4. Schema maintenance API + safe editor UI with preview diff.
5. Existing-wiki Karpathy audit scorecard and remediation checklist.

Priority 3
6. Ingestion discussion loop with LLM and operator comments/approvals.
7. Change recommendations auto-written into Charter Notes + `log.md`.

---

## 9) Known constraints

- Wiki root path is restricted under:
  `/mnt/c/Users/cfkle/My Drive/cfk master/01-wikis`
- Admin role is required for write operations.
- Some tile actions are currently placeholders and do not mutate content.

---

## 10) Quick troubleshooting

- If wizard endpoints fail after code changes: restart `custom-web-ui.service`.
- If tile actions appear no-op: this is expected for ingest/query/lint in current build.
- If charter cannot load: verify selected tile and `setup-interview.md` path exists.
