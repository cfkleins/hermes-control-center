# LLM Wiki Tab — One-Page Summary

## What it is
The LLM Wikis tab is a Karpathy-style wiki bootstrap and operations panel for subject wikis under:
`/mnt/c/Users/cfkle/My Drive/cfk master/01-wikis`

## What works now
- Create/update wiki tiles (status, health, notes, index timestamp).
- 6-step wizard modal to define scope/path/schema seeds.
- Blueprint validation (readiness scoring).
- Wiki initialization with scaffold + starter docs:
  - `SCHEMA.md`
  - `index.md`
  - `log.md`
  - `setup-interview.md` (used as Charter & Intake Notes)
- Charter load/edit/save workflow.
- Tile KPI flags: path status, charter status, stale age.

## What does NOT fully work yet
- No full conformance audit for existing wikis vs Karpathy method.
- No dedicated schema maintenance API/UI for `SCHEMA.md` diff-safe updates.
- No complete ingest/query/lint backend pipeline from tile buttons.
- No ingestion-time LLM discussion/approval loop yet.

## Current tile button meanings
- **Load to Editor**: edit tile metadata.
- **Open Charter**: opens charter notes markdown for selected wiki.
- **Mark Indexed Now**: updates `last_indexed_at`.
- **Ingest Source / Ask Wiki / Lint Health**: placeholders (status messaging only right now).

## Minimal best-practice workflow today
1. Open wizard, define scope/taxonomy/seeds/sources.
2. Validate blueprint.
3. Initialize wiki.
4. Refine Charter Notes.
5. Manually curate/ingest files to `raw/*` until ingest pipeline lands.
6. Log changes in `log.md`.

## Keyboard/UX status
- Wizard is modal.
- Escape closes modal.
- Focus trap active while modal is open.

## Next upgrades to prioritize
1. Implement real ingest pipeline.
2. Implement query pipeline.
3. Implement lint/conformance engine.
4. Add schema editor API + diff review.
5. Add ingestion discussion loop with LLM approvals/comments.
