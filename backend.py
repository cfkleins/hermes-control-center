from datetime import datetime, timezone, timedelta
from itertools import count
from pathlib import Path
from random import randint, uniform
import json
import re
import secrets

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

app = FastAPI(title="Custom Ops UI Backend")

SETTINGS_PATH = Path("settings.json")
OPERATORS_PATH = Path("operators.json")
DEFAULT_SETTINGS = {
    "provider": "openai",
    "model": "gpt-5.3-codex",
    "voice_profile": "quality",
    "timeline_refresh_seconds": 5,
}
DEFAULT_OPERATORS = {
    "operators": [
        {"username": "admin", "pin": "1234", "role": "admin"},
        {"username": "ops", "pin": "1111", "role": "operator"},
    ]
}

SESSION_IDLE_TIMEOUT_SECONDS = 15 * 60
SESSION_ABSOLUTE_TIMEOUT_SECONDS = 8 * 60 * 60
WIKI_ROOT_PATH = Path("/mnt/c/Users/cfkle/My Drive/cfk master/01-wikis")
sessions: dict[str, dict] = {}
prompt_id_counter = count(1)
voice_id_counter = count(1)
timeline_id_counter = count(1)
alert_id_counter = count(1)
template_id_counter = count(1)

operator_state: dict[str, dict] = {}


def _default_llm_wikis() -> list[dict]:
    now_iso = datetime.now(timezone.utc).isoformat()
    return [
        {
            "id": 1,
            "subject": "GranSyn Wiki",
            "status": "active",
            "health": "green",
            "last_indexed_at": now_iso,
            "notes": "Existing wiki discovered under 01-wikis.",
            "wiki_slug": "gransyn-wiki",
            "wiki_path": str(WIKI_ROOT_PATH / "gransyn-wiki"),
            "interview_status": "completed",
        },
        {
            "id": 2,
            "subject": "Journal Wiki",
            "status": "active",
            "health": "green",
            "last_indexed_at": now_iso,
            "notes": "Existing wiki discovered under 01-wikis.",
            "wiki_slug": "journal-wiki",
            "wiki_path": str(WIKI_ROOT_PATH / "journal-wiki"),
            "interview_status": "completed",
        },
        {
            "id": 3,
            "subject": "Security",
            "status": "maintenance",
            "health": "yellow",
            "last_indexed_at": now_iso,
            "notes": "Session and RBAC hardening updates in progress.",
            "wiki_slug": "security",
            "wiki_path": str(WIKI_ROOT_PATH / "security"),
            "interview_status": "pending",
        },
    ]


class LoginPayload(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    pin: str = Field(min_length=1, max_length=20)


class PromptRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)


class VoiceCommandRequest(BaseModel):
    transcript: str = Field(min_length=1, max_length=2000)


class SettingsPayload(BaseModel):
    provider: str = Field(min_length=1, max_length=120)
    model: str = Field(min_length=1, max_length=200)
    voice_profile: str = Field(min_length=1, max_length=80)
    timeline_refresh_seconds: int = Field(ge=2, le=60)


class AlertActionPayload(BaseModel):
    action: str = Field(pattern="^(ack|snooze|resolve)$")


class PromptTemplatePayload(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    prompt: str = Field(min_length=1, max_length=4000)


class LlmWikiPayload(BaseModel):
    subject: str = Field(min_length=1, max_length=120)
    status: str = Field(pattern="^(planned|active|blocked|maintenance|complete)$")
    health: str = Field(pattern="^(green|yellow|red)$")
    last_indexed_at: str = Field(min_length=1, max_length=64)
    notes: str = Field(min_length=0, max_length=500)


class WikiInterviewPayload(BaseModel):
    content: str = Field(min_length=0, max_length=100000)
    status: str = Field(pattern="^(pending|in_progress|completed)$")


class WikiSchemaPayload(BaseModel):
    content: str = Field(min_length=1, max_length=300000)


class WikiBlueprintPayload(BaseModel):
    subject: str = Field(min_length=1, max_length=120)
    scope: str = Field(min_length=1, max_length=2000)
    out_of_scope: str = Field(min_length=0, max_length=2000, default="")
    wiki_slug: str = Field(min_length=1, max_length=120)
    wiki_root_path: str = Field(min_length=1, max_length=500)
    status: str = Field(pattern="^(planned|active|blocked|maintenance|complete)$", default="planned")
    health: str = Field(pattern="^(green|yellow|red)$", default="green")
    notes: str = Field(min_length=0, max_length=500, default="")
    seed_sources: list[str] = Field(default_factory=list)
    seed_entities: list[str] = Field(default_factory=list)
    seed_concepts: list[str] = Field(default_factory=list)
    taxonomy_tags: list[str] = Field(default_factory=list)


class WikiIngestPayload(BaseModel):
    source: str = Field(min_length=1, max_length=2000)
    bucket: str = Field(pattern="^(articles|papers|transcripts|assets)$", default="articles")
    note: str = Field(min_length=0, max_length=2000, default="")


class WikiAskPayload(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class WikiScaffoldPayload(BaseModel):
    targets: list[str] = Field(default_factory=list)


class WikiRepairRunPayload(BaseModel):
    include_orphan_fix_guidance: bool = True


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _load_json(path: Path, default: dict) -> dict:
    if not path.exists():
        path.write_text(json.dumps(default, indent=2), encoding="utf-8")
        return default.copy()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data
    except Exception:
        path.write_text(json.dumps(default, indent=2), encoding="utf-8")
        return default.copy()


def _load_global_settings() -> dict:
    loaded = _load_json(SETTINGS_PATH, DEFAULT_SETTINGS)
    merged = DEFAULT_SETTINGS.copy()
    merged.update({k: loaded[k] for k in DEFAULT_SETTINGS.keys() if k in loaded})
    return merged


def _save_global_settings(data: dict) -> None:
    SETTINGS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _load_operators() -> list[dict]:
    data = _load_json(OPERATORS_PATH, DEFAULT_OPERATORS)
    return data.get("operators", [])


def _get_operator_record(username: str) -> dict | None:
    operators = _load_operators()
    return next((op for op in operators if op.get("username") == username), None)


def _get_operator_role(username: str) -> str:
    record = _get_operator_record(username)
    if record and record.get("role") in {"admin", "operator"}:
        return str(record["role"])
    return "admin" if username == "admin" else "operator"


def _ensure_operator_state(username: str) -> dict:
    if username not in operator_state:
        operator_state[username] = {
            "prompt_history": [],
            "voice_events": [],
            "timeline": [],
            "alerts": [],
            "alert_actions": {},
            "prompt_templates": [],
            "llm_wikis": _default_llm_wikis(),
            "settings": _load_global_settings(),
        }
    return operator_state[username]


def _utcnow_ts() -> float:
    return datetime.now(timezone.utc).timestamp()


def _expires_at_iso(last_seen_ts: float) -> str:
    expires_ts = last_seen_ts + SESSION_IDLE_TIMEOUT_SECONDS
    return datetime.fromtimestamp(expires_ts, tz=timezone.utc).isoformat()


def _absolute_expires_at_iso(created_ts: float) -> str:
    expires_ts = created_ts + SESSION_ABSOLUTE_TIMEOUT_SECONDS
    return datetime.fromtimestamp(expires_ts, tz=timezone.utc).isoformat()


def _ts_iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _purge_expired_sessions() -> None:
    now_ts = _utcnow_ts()
    expired_tokens = [
        token
        for token, session in sessions.items()
        if (
            now_ts - float(session.get("last_seen_ts", 0.0)) > SESSION_IDLE_TIMEOUT_SECONDS
            or now_ts - float(session.get("created_ts", 0.0)) > SESSION_ABSOLUTE_TIMEOUT_SECONDS
        )
    ]
    for token in expired_tokens:
        sessions.pop(token, None)


def _create_session(username: str) -> tuple[str, dict]:
    token = secrets.token_urlsafe(24)
    now_ts = _utcnow_ts()
    session = {"username": username, "created_ts": now_ts, "last_seen_ts": now_ts}
    sessions[token] = session
    return token, session


def _touch_session(token: str) -> dict:
    session = sessions[token]
    session["last_seen_ts"] = _utcnow_ts()
    return session


def _revoke_session(token: str) -> None:
    sessions.pop(token, None)


def _require_operator(x_session_token: str | None) -> str:
    if not x_session_token:
        raise HTTPException(status_code=401, detail="Missing session token")
    _purge_expired_sessions()
    session = sessions.get(x_session_token)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid session token")
    username = str(session.get("username", ""))
    if not username:
        _revoke_session(x_session_token)
        raise HTTPException(status_code=401, detail="Invalid session token")
    _touch_session(x_session_token)
    _ensure_operator_state(username)
    return username


def _require_admin(username: str) -> None:
    if _get_operator_role(username) != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")


def _add_timeline_event(username: str, kind: str, message: str, details: dict | None = None) -> dict:
    state = _ensure_operator_state(username)
    entry = {
        "id": next(timeline_id_counter),
        "kind": kind,
        "message": message,
        "details": details or {},
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    state["timeline"].insert(0, entry)
    del state["timeline"][50:]
    return entry


def _run_prompt(username: str, prompt_text: str, max_retries: int = 2) -> dict:
    state = _ensure_operator_state(username)
    attempt = 1
    status = "success"
    response = f"Processed prompt: {prompt_text[:120]}"

    if "retry" in prompt_text.lower():
        while attempt <= max_retries:
            if attempt == max_retries:
                response = f"Recovered after retry {attempt - 1}: {prompt_text[:120]}"
                break
            attempt += 1

    entry = {
        "id": next(prompt_id_counter),
        "prompt": prompt_text,
        "status": status,
        "attempts": attempt,
        "response": response,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    state["prompt_history"].insert(0, entry)
    del state["prompt_history"][20:]
    _add_timeline_event(
        username,
        "prompt",
        f"Prompt #{entry['id']} completed ({status})",
        {"attempts": attempt, "preview": prompt_text[:80]},
    )
    return entry


def _upsert_alert(state: dict, severity: str, code: str, message: str) -> None:
    action_state = state.get("alert_actions", {}).get(code, "open")
    for alert in state["alerts"]:
        if alert["code"] == code:
            alert.update(
                {
                    "severity": severity,
                    "message": message,
                    "action_state": action_state,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            return
    state["alerts"].insert(
        0,
        {
            "id": next(alert_id_counter),
            "severity": severity,
            "code": code,
            "message": message,
            "action_state": action_state,
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    )


def _refresh_alerts(username: str, metrics: dict) -> list[dict]:
    state = _ensure_operator_state(username)
    state["alerts"] = []

    if metrics["tasks_running"] >= 5:
        _upsert_alert(
            state,
            "warning",
            "task_pressure",
            f"High active task load ({metrics['tasks_running']})",
        )
    if metrics["avg_response_seconds"] >= 1.5:
        _upsert_alert(
            state,
            "warning",
            "latency_drift",
            f"Average response elevated ({metrics['avg_response_seconds']}s)",
        )
    if metrics["error_rate_percent"] >= 0.6:
        _upsert_alert(
            state,
            "critical",
            "error_spike",
            f"Error rate spike ({metrics['error_rate_percent']}%)",
        )

    if not state["alerts"]:
        _upsert_alert(state, "info", "all_clear", "All systems within nominal range")

    state["alerts"] = [a for a in state["alerts"] if a.get("action_state") != "resolved"]
    del state["alerts"][10:]
    return state["alerts"]


def _apply_alert_action(username: str, alert_id: int, action: str) -> dict:
    _require_admin(username)
    state = _ensure_operator_state(username)
    alert = next((a for a in state["alerts"] if a["id"] == alert_id), None)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    code = alert["code"]
    if action == "ack":
        state["alert_actions"][code] = "acknowledged"
    elif action == "snooze":
        state["alert_actions"][code] = "snoozed"
    elif action == "resolve":
        state["alert_actions"][code] = "resolved"

    alert["action_state"] = state["alert_actions"][code]
    _add_timeline_event(
        username,
        "alert",
        f"Alert #{alert_id} {state['alert_actions'][code]}",
        {"code": code, "action": action},
    )

    if state["alert_actions"][code] == "resolved":
        state["alerts"] = [a for a in state["alerts"] if a["id"] != alert_id]

    return {
        "id": alert_id,
        "code": code,
        "action_state": state["alert_actions"][code],
    }


def _create_prompt_template(username: str, name: str, prompt: str) -> dict:
    state = _ensure_operator_state(username)
    entry = {
        "id": next(template_id_counter),
        "name": name.strip(),
        "prompt": prompt.strip(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    state["prompt_templates"].insert(0, entry)
    del state["prompt_templates"][25:]
    _add_timeline_event(username, "prompt", f"Template created: {entry['name']}", {"template_id": entry["id"]})
    return entry


def _delete_prompt_template(username: str, template_id: int) -> None:
    _require_admin(username)
    state = _ensure_operator_state(username)
    before = len(state["prompt_templates"])
    state["prompt_templates"] = [t for t in state["prompt_templates"] if t["id"] != template_id]
    if len(state["prompt_templates"]) == before:
        raise HTTPException(status_code=404, detail="Template not found")
    _add_timeline_event(username, "prompt", f"Template deleted: #{template_id}", {"template_id": template_id})


def _slugify(value: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return base or "wiki"


def _normalize_seed_list(items: list[str], max_items: int = 20) -> list[str]:
    out: list[str] = []
    for item in items or []:
        cleaned = str(item).strip()
        if cleaned and cleaned not in out:
            out.append(cleaned)
        if len(out) >= max_items:
            break
    return out


def _resolve_wiki_dir(root_path: str, slug: str) -> Path:
    base = Path(root_path).expanduser()
    if not str(base.resolve()).startswith(str(WIKI_ROOT_PATH.resolve())):
        raise HTTPException(status_code=400, detail="wiki_root_path must stay under configured wiki root")
    return base / slug


def _build_karpathy_scaffold(
    *,
    subject: str,
    scope: str,
    out_of_scope: str,
    tags: list[str],
    seed_entities: list[str],
    seed_concepts: list[str],
    seed_sources: list[str],
    wiki_dir: Path,
    slug: str,
) -> dict:
    created_at = datetime.now(timezone.utc)
    created_iso = created_at.isoformat()
    created_day = created_at.date().isoformat()

    tags_block = "\n".join([f"- {tag}" for tag in tags]) if tags else "- model\n- architecture\n- dataset\n- benchmark\n- person\n- company\n- technique\n- comparison\n- timeline\n- open-question"
    seed_entities_block = "\n".join([f"- {item}" for item in seed_entities]) if seed_entities else "- (none yet)"
    seed_concepts_block = "\n".join([f"- {item}" for item in seed_concepts]) if seed_concepts else "- (none yet)"
    seed_sources_block = "\n".join([f"- {item}" for item in seed_sources]) if seed_sources else "- (none yet)"

    schema = f"""# Wiki Schema

## Domain
{subject}

## Scope
{scope}

## Out of Scope
{out_of_scope or '(not specified)'}

## Conventions
- File names: lowercase-kebab-case
- Every page uses YAML frontmatter
- Every page should include at least 2 outbound [[wikilinks]]
- Log all changes in log.md
- Add new pages to index.md immediately

## Frontmatter
```yaml
---
title: Page Title
created: YYYY-MM-DD
updated: YYYY-MM-DD
type: entity | concept | comparison | query | summary
tags: []
sources: []
---
```

## Tag Taxonomy
{tags_block}

## Page Thresholds
- Create a page when concept/entity appears in 2+ sources OR is central to one source
- Add to existing page for passing mentions
- Split page over ~200 lines into sub-pages
"""

    index_md = f"""# Wiki Index

> Last updated: {created_day} | Total pages: 0

## Entities

## Concepts

## Comparisons

## Queries
"""

    log_md = f"""# Wiki Log

## [{created_day}] create | Wiki initialized
- Subject: {subject}
- Process: karpathy-llm-wiki bootstrap wizard
- Root: {wiki_dir}
- Slug: {slug}
"""

    interview_md = f"""# Wiki Charter & Intake Notes — {subject}

_Status: pending_

This document is generated from the wizard and serves two purposes:
1) preserve schema-driving decisions used to create SCHEMA.md, and
2) track post-init operating notes as the wiki evolves.

## Schema-driving intake (captured by wizard)
- Domain scope: {scope}
- Out of scope: {out_of_scope or '(not specified)'}

### Taxonomy tags used for SCHEMA.md
{tags_block}

### Seed entities (schema and index priorities)
{seed_entities_block}

### Seed concepts (schema and index priorities)
{seed_concepts_block}

### Seed sources (initial ingest queue)
{seed_sources_block}

## Follow-up charter notes (post-init)
Use this section for changes after initialization:
- taxonomy refinements
- quality bar updates
- ingest strategy decisions
- curation policies

## Optional prompts for future refinement
1. Which schema fields need tightening after first ingest?
2. Which entity/concept types are over- or under-represented?
3. What quality bar should trigger "complete" status?

Created at: {created_iso}
"""

    return {
        "SCHEMA.md": schema,
        "index.md": index_md,
        "log.md": log_md,
        "setup-interview.md": interview_md,
    }


def _init_karpathy_wiki_structure(subject: str) -> dict:
    slug = _slugify(subject)
    return _init_karpathy_wiki_from_blueprint(
        subject=subject,
        scope=f"Focused wiki for {subject}",
        out_of_scope="",
        wiki_slug=slug,
        wiki_root_path=str(WIKI_ROOT_PATH),
        status="planned",
        health="green",
        notes="",
        seed_sources=[],
        seed_entities=[],
        seed_concepts=[],
        taxonomy_tags=[],
    )


def _init_karpathy_wiki_from_blueprint(**kwargs) -> dict:
    subject = str(kwargs.get("subject", "")).strip()
    slug = _slugify(str(kwargs.get("wiki_slug", "") or subject))
    wiki_root_path = str(kwargs.get("wiki_root_path", str(WIKI_ROOT_PATH))).strip() or str(WIKI_ROOT_PATH)
    wiki_dir = _resolve_wiki_dir(wiki_root_path, slug)

    scope = str(kwargs.get("scope", "")).strip() or f"Focused wiki for {subject}"
    out_of_scope = str(kwargs.get("out_of_scope", "")).strip()
    tags = _normalize_seed_list(kwargs.get("taxonomy_tags", []), max_items=40)
    seed_entities = _normalize_seed_list(kwargs.get("seed_entities", []), max_items=30)
    seed_concepts = _normalize_seed_list(kwargs.get("seed_concepts", []), max_items=30)
    seed_sources = _normalize_seed_list(kwargs.get("seed_sources", []), max_items=50)

    (wiki_dir / "raw" / "articles").mkdir(parents=True, exist_ok=True)
    (wiki_dir / "raw" / "papers").mkdir(parents=True, exist_ok=True)
    (wiki_dir / "raw" / "transcripts").mkdir(parents=True, exist_ok=True)
    (wiki_dir / "raw" / "assets").mkdir(parents=True, exist_ok=True)
    (wiki_dir / "entities").mkdir(parents=True, exist_ok=True)
    (wiki_dir / "concepts").mkdir(parents=True, exist_ok=True)
    (wiki_dir / "comparisons").mkdir(parents=True, exist_ok=True)
    (wiki_dir / "queries").mkdir(parents=True, exist_ok=True)

    files = _build_karpathy_scaffold(
        subject=subject,
        scope=scope,
        out_of_scope=out_of_scope,
        tags=tags,
        seed_entities=seed_entities,
        seed_concepts=seed_concepts,
        seed_sources=seed_sources,
        wiki_dir=wiki_dir,
        slug=slug,
    )
    created_files: list[str] = []
    for filename, content in files.items():
        path = wiki_dir / filename
        path.write_text(content, encoding="utf-8")
        created_files.append(str(path))

    return {
        "wiki_slug": slug,
        "wiki_path": str(wiki_dir),
        "interview_path": str(wiki_dir / "setup-interview.md"),
        "interview_status": "pending",
        "created_files": created_files,
    }


def _ensure_existing_wiki_tiles(state: dict) -> None:
    now_iso = datetime.now(timezone.utc).isoformat()
    expected = [
        {
            "subject": "GranSyn Wiki",
            "wiki_slug": "gransyn-wiki",
            "wiki_path": str(WIKI_ROOT_PATH / "gransyn-wiki"),
            "status": "active",
            "health": "green",
            "interview_status": "completed",
            "notes": "Existing wiki discovered under 01-wikis.",
        },
        {
            "subject": "Journal Wiki",
            "wiki_slug": "journal-wiki",
            "wiki_path": str(WIKI_ROOT_PATH / "journal-wiki"),
            "status": "active",
            "health": "green",
            "interview_status": "completed",
            "notes": "Existing wiki discovered under 01-wikis.",
        },
    ]

    current = list(state.get("llm_wikis", []))
    by_slug = {str(item.get("wiki_slug", "")): item for item in current}
    next_id = max((int(item.get("id", 0)) for item in current), default=0) + 1

    normalized_front: list[dict] = []
    for item in expected:
        existing = by_slug.get(item["wiki_slug"])
        if existing:
            existing.update(
                {
                    "subject": item["subject"],
                    "wiki_slug": item["wiki_slug"],
                    "wiki_path": item["wiki_path"],
                    "status": item["status"],
                    "health": item["health"],
                    "interview_status": item["interview_status"],
                    "notes": item["notes"],
                    "last_indexed_at": existing.get("last_indexed_at") or now_iso,
                }
            )
            normalized_front.append(existing)
            continue

        created = {
            "id": next_id,
            "subject": item["subject"],
            "status": item["status"],
            "health": item["health"],
            "last_indexed_at": now_iso,
            "notes": item["notes"],
            "wiki_slug": item["wiki_slug"],
            "wiki_path": item["wiki_path"],
            "interview_status": item["interview_status"],
        }
        next_id += 1
        normalized_front.append(created)

    expected_slugs = {item["wiki_slug"] for item in expected}
    rest = [item for item in current if str(item.get("wiki_slug", "")) not in expected_slugs]
    state["llm_wikis"] = normalized_front + rest


def _parse_iso_datetime(value: str) -> datetime | None:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        normalized = raw.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _wiki_kpi_view(item: dict) -> dict:
    now = datetime.now(timezone.utc)
    last_indexed_raw = str(item.get("last_indexed_at", ""))
    last_indexed_dt = _parse_iso_datetime(last_indexed_raw)

    indexed_age_minutes: int | None = None
    indexed_age_bucket = "unknown"
    is_stale = False
    if last_indexed_dt is not None:
        delta = now - last_indexed_dt
        indexed_age_minutes = max(0, int(delta.total_seconds() // 60))
        if delta <= timedelta(hours=24):
            indexed_age_bucket = "fresh"
        elif delta <= timedelta(hours=72):
            indexed_age_bucket = "aging"
        else:
            indexed_age_bucket = "stale"
            is_stale = True

    wiki_path = Path(str(item.get("wiki_path", "")).strip())
    path_exists = wiki_path.exists() if str(wiki_path) else False

    interview_path = Path(str(item.get("interview_path") or "").strip())
    if not str(interview_path):
        interview_path = wiki_path / "setup-interview.md"
    interview_exists = interview_path.exists() if str(interview_path) else False

    interview_status = str(item.get("interview_status", "pending"))
    interview_complete = interview_status == "completed"

    return {
        **item,
        "indexed_age_minutes": indexed_age_minutes,
        "indexed_age_bucket": indexed_age_bucket,
        "is_stale": is_stale,
        "path_exists": path_exists,
        "interview_path": str(interview_path),
        "interview_exists": interview_exists,
        "interview_complete": interview_complete,
    }


def _list_llm_wikis(username: str, limit: int) -> list[dict]:
    state = _ensure_operator_state(username)
    _ensure_existing_wiki_tiles(state)
    safe_limit = max(1, min(limit, 50))
    return [_wiki_kpi_view(item) for item in state["llm_wikis"][:safe_limit]]


def _create_llm_wiki(username: str, payload: LlmWikiPayload) -> dict:
    _require_admin(username)
    state = _ensure_operator_state(username)
    next_id = max((int(item.get("id", 0)) for item in state["llm_wikis"]), default=0) + 1
    bootstrap = _init_karpathy_wiki_structure(payload.subject)
    item = {
        "id": next_id,
        "subject": payload.subject.strip(),
        "status": payload.status,
        "health": payload.health,
        "last_indexed_at": payload.last_indexed_at,
        "notes": payload.notes.strip(),
        **bootstrap,
    }
    state["llm_wikis"].insert(0, item)
    del state["llm_wikis"][50:]
    _add_timeline_event(
        username,
        "wiki",
        f"Wiki created: {item['subject']} (Karpathy init + charter notes)",
        {"wiki_id": item["id"], "wiki_path": item["wiki_path"]},
    )
    return item


def _update_llm_wiki(username: str, wiki_id: int, payload: LlmWikiPayload) -> dict:
    _require_admin(username)
    state = _ensure_operator_state(username)
    wiki = next((item for item in state["llm_wikis"] if int(item.get("id", -1)) == wiki_id), None)
    if not wiki:
        raise HTTPException(status_code=404, detail="Wiki not found")
    wiki.update(
        {
            "subject": payload.subject.strip(),
            "status": payload.status,
            "health": payload.health,
            "last_indexed_at": payload.last_indexed_at,
            "notes": payload.notes.strip(),
        }
    )
    _add_timeline_event(username, "wiki", f"Wiki updated: {wiki['subject']}", {"wiki_id": wiki_id})
    return wiki


def _find_wiki(username: str, wiki_id: int) -> dict:
    state = _ensure_operator_state(username)
    _ensure_existing_wiki_tiles(state)
    wiki = next((item for item in state["llm_wikis"] if int(item.get("id", -1)) == wiki_id), None)
    if not wiki:
        raise HTTPException(status_code=404, detail="Wiki not found")
    return wiki


def _resolve_interview_path(wiki: dict) -> Path:
    raw = str(wiki.get("interview_path") or "").strip()
    path = Path(raw) if raw else Path(str(wiki.get("wiki_path", ""))) / "setup-interview.md"
    if not str(path.resolve()).startswith(str(WIKI_ROOT_PATH.resolve())):
        raise HTTPException(status_code=400, detail="Interview path outside allowed wiki root")
    return path


def _resolve_wiki_path(wiki: dict) -> Path:
    raw = str(wiki.get("wiki_path", "")).strip()
    if not raw:
        raise HTTPException(status_code=400, detail="Wiki has no path")
    wiki_path = Path(raw)
    if not str(wiki_path.resolve()).startswith(str(WIKI_ROOT_PATH.resolve())):
        raise HTTPException(status_code=400, detail="Wiki path outside allowed wiki root")
    return wiki_path


def _append_wiki_log(wiki_path: Path, line: str) -> None:
    log_path = wiki_path / "log.md"
    if not log_path.exists():
        log_path.write_text("# Log\n\n", encoding="utf-8")
    with log_path.open("a", encoding="utf-8") as f:
        f.write(f"- {line}\n")


def _ingest_wiki_source(username: str, wiki_id: int, payload: WikiIngestPayload) -> dict:
    _require_admin(username)
    wiki = _find_wiki(username, wiki_id)
    wiki_path = _resolve_wiki_path(wiki)
    source = payload.source.strip()
    bucket = payload.bucket
    now = datetime.now(timezone.utc)

    bucket_dir = wiki_path / "raw" / bucket
    bucket_dir.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r"[^a-z0-9]+", "-", source.lower()).strip("-")[:48] or "source"
    ingest_filename = f"ingest-{now.strftime('%Y%m%dT%H%M%SZ')}-{stem}.md"
    ingest_path = bucket_dir / ingest_filename
    ingest_md = (
        f"# Ingest Source\n\n"
        f"- Source: {source}\n"
        f"- Bucket: {bucket}\n"
        f"- Ingested at: {now.isoformat()}\n"
        f"- Ingested by: {username}\n"
        f"- Note: {payload.note.strip() or '(none)'}\n"
    )
    ingest_path.write_text(ingest_md, encoding="utf-8")

    _append_wiki_log(
        wiki_path,
        f"[{now.isoformat()}] source ingested into raw/{bucket}: {source} ({ingest_filename})",
    )
    wiki["last_indexed_at"] = now.isoformat()
    _add_timeline_event(
        username,
        "wiki",
        f"Source ingested for {wiki.get('subject', 'Unknown Wiki')}",
        {"wiki_id": wiki_id, "bucket": bucket, "source": source, "path": str(ingest_path)},
    )
    return {
        "wiki_id": wiki_id,
        "subject": wiki.get("subject", ""),
        "bucket": bucket,
        "source": source,
        "ingest_path": str(ingest_path),
        "updated_last_indexed_at": wiki["last_indexed_at"],
    }


def _ask_wiki(username: str, wiki_id: int, payload: WikiAskPayload) -> dict:
    wiki = _find_wiki(username, wiki_id)
    wiki_path = _resolve_wiki_path(wiki)
    question = payload.question.strip()
    q_terms = [t.lower() for t in re.findall(r"[a-zA-Z0-9_\-]{3,}", question)][:8]

    candidate_files = [
        wiki_path / "SCHEMA.md",
        wiki_path / "index.md",
        wiki_path / "setup-interview.md",
        wiki_path / "log.md",
    ]
    snippets: list[dict] = []
    for file_path in candidate_files:
        if not file_path.exists():
            continue
        lines = file_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        for idx, line in enumerate(lines, start=1):
            lowered = line.lower()
            if q_terms and any(term in lowered for term in q_terms):
                snippets.append({"path": str(file_path), "line": idx, "text": line.strip()[:240]})
                if len(snippets) >= 12:
                    break
        if len(snippets) >= 12:
            break

    if snippets:
        preview = "\n".join([f"- {s['path']}:{s['line']} → {s['text']}" for s in snippets[:6]])
        answer = (
            "Phase-1 wiki query result (keyword match):\n"
            f"Question: {question}\n"
            "Top matching lines:\n"
            f"{preview}"
        )
    else:
        answer = (
            "Phase-1 wiki query could not find direct keyword matches in SCHEMA.md/index.md/"
            "setup-interview.md/log.md."
        )

    _add_timeline_event(
        username,
        "wiki",
        f"Wiki queried: {wiki.get('subject', 'Unknown Wiki')}",
        {"wiki_id": wiki_id, "question": question[:180], "matches": len(snippets)},
    )
    return {
        "wiki_id": wiki_id,
        "subject": wiki.get("subject", ""),
        "question": question,
        "answer": answer,
        "matches": snippets[:12],
    }


def _lint_wiki(username: str, wiki_id: int) -> dict:
    wiki = _find_wiki(username, wiki_id)
    wiki_path = _resolve_wiki_path(wiki)
    required_files = ["SCHEMA.md", "index.md", "log.md", "setup-interview.md"]
    required_dirs = ["raw/articles", "raw/papers", "raw/transcripts", "raw/assets"]

    file_checks = [{"path": name, "exists": (wiki_path / name).exists()} for name in required_files]
    dir_checks = [{"path": name, "exists": (wiki_path / name).exists()} for name in required_dirs]
    missing_files = [c["path"] for c in file_checks if not c["exists"]]
    missing_dirs = [c["path"] for c in dir_checks if not c["exists"]]

    schema_text = ""
    schema_path = wiki_path / "SCHEMA.md"
    if schema_path.exists():
        schema_text = schema_path.read_text(encoding="utf-8", errors="ignore")
    schema_lower = schema_text.lower()
    taxonomy_ok = "taxonomy" in schema_lower or "tag" in schema_lower
    crosslink_ok = "[[" in schema_text
    schema_entity_ok = "entity" in schema_lower
    schema_crosslink_section_ok = "crosslink" in schema_lower

    md_files = [p for p in wiki_path.rglob("*.md") if "raw" not in p.relative_to(wiki_path).parts]
    inbound_counts: dict[str, int] = {}
    outbound_counts: dict[str, int] = {}
    page_names: dict[str, str] = {}
    frontmatter_files = 0
    wikilink_re = re.compile(r"\[\[([^\]|#]+)")

    for p in md_files:
        rel = str(p.relative_to(wiki_path))
        name = p.stem.strip().lower()
        page_names[name] = rel
        inbound_counts.setdefault(name, 0)
        outbound_counts.setdefault(name, 0)

    for p in md_files:
        name = p.stem.strip().lower()
        text = p.read_text(encoding="utf-8", errors="ignore")
        if text.lstrip().startswith("---\n"):
            frontmatter_files += 1
        refs = [m.group(1).strip().lower() for m in wikilink_re.finditer(text)]
        outbound_counts[name] = len(refs)
        for ref in refs:
            inbound_counts[ref] = inbound_counts.get(ref, 0) + 1

    exempt = {"index", "log", "schema", "setup-interview"}
    orphan_pages = [page_names[n] for n in page_names if n not in exempt and inbound_counts.get(n, 0) == 0]
    total_pages = len(page_names)
    total_outbound = sum(outbound_counts.values())
    frontmatter_ratio = (frontmatter_files / total_pages) if total_pages else 0.0
    orphan_ratio = (len(orphan_pages) / total_pages) if total_pages else 0.0
    link_density = (total_outbound / total_pages) if total_pages else 0.0
    graph_drift = orphan_ratio > 0.4 or link_density < 0.3

    score = 100 - (len(missing_files) * 15) - (len(missing_dirs) * 10)
    score -= 8 if not taxonomy_ok else 0
    score -= 8 if not crosslink_ok else 0
    score -= 8 if not schema_entity_ok else 0
    score -= 8 if not schema_crosslink_section_ok else 0
    score -= min(20, len(orphan_pages) * 2)
    score -= 10 if graph_drift else 0
    score -= 8 if frontmatter_ratio < 0.5 else 0
    score = max(0, score)
    health = "green" if score >= 85 else "yellow" if score >= 60 else "red"

    wiki["health"] = health
    _add_timeline_event(
        username,
        "wiki",
        f"Wiki linted: {wiki.get('subject', 'Unknown Wiki')} ({health}, {score})",
        {
            "wiki_id": wiki_id,
            "score": score,
            "health": health,
            "missing_files": missing_files,
            "missing_dirs": missing_dirs,
            "orphan_count": len(orphan_pages),
            "frontmatter_ratio": round(frontmatter_ratio, 3),
            "link_density": round(link_density, 3),
        },
    )
    return {
        "wiki_id": wiki_id,
        "subject": wiki.get("subject", ""),
        "wiki_path": str(wiki_path),
        "score": score,
        "health": health,
        "checks": {
            "required_files": file_checks,
            "required_dirs": dir_checks,
            "taxonomy_markers_present": taxonomy_ok,
            "crosslink_marker_present": crosslink_ok,
            "schema_entity_markers_present": schema_entity_ok,
            "schema_crosslink_section_present": schema_crosslink_section_ok,
            "frontmatter_ratio": round(frontmatter_ratio, 3),
            "link_density": round(link_density, 3),
            "graph_drift_detected": graph_drift,
            "orphan_pages": orphan_pages[:100],
        },
        "missing": {"files": missing_files, "dirs": missing_dirs},
    }


def _get_wiki_lint_history(username: str, wiki_id: int, limit: int = 20) -> dict:
    wiki = _find_wiki(username, wiki_id)
    state = _ensure_operator_state(username)
    safe_limit = max(1, min(limit, 100))
    rows: list[dict] = []
    for item in state.get("timeline", []):
        if item.get("kind") != "wiki":
            continue
        details = item.get("details") or {}
        if int(details.get("wiki_id", -1)) != int(wiki_id):
            continue
        if "score" not in details or "health" not in details:
            continue
        rows.append(
            {
                "created_at": item.get("created_at"),
                "score": details.get("score"),
                "health": details.get("health"),
                "orphan_count": details.get("orphan_count", 0),
                "frontmatter_ratio": details.get("frontmatter_ratio", 0),
                "link_density": details.get("link_density", 0),
            }
        )
        if len(rows) >= safe_limit:
            break
    trend = "stable"
    if len(rows) >= 2:
        newest = int(rows[0].get("score") or 0)
        oldest = int(rows[-1].get("score") or 0)
        delta = newest - oldest
        if delta >= 5:
            trend = "improving"
        elif delta <= -5:
            trend = "degrading"
    return {
        "wiki_id": wiki_id,
        "subject": wiki.get("subject", ""),
        "trend": trend,
        "items": rows,
    }


def _build_conformance_playbook(username: str, wiki_id: int) -> dict:
    lint = _lint_wiki(username, wiki_id)
    checks = lint.get("checks", {})
    missing = lint.get("missing", {})
    steps: list[dict] = []

    if missing.get("files") or missing.get("dirs"):
        steps.append(
            {
                "id": "repair-scaffold",
                "title": "Create missing scaffold",
                "reason": "Required wiki files or directories are missing.",
                "actions": [
                    "Use Create Missing Scaffold (bulk) in Lint modal.",
                    "Re-run lint and confirm missing files/dirs are zero.",
                ],
            }
        )

    if not checks.get("taxonomy_markers_present") or not checks.get("schema_entity_markers_present"):
        steps.append(
            {
                "id": "repair-schema-taxonomy",
                "title": "Strengthen SCHEMA taxonomy/entities",
                "reason": "Schema taxonomy or entity markers are weak/missing.",
                "actions": [
                    "Open SCHEMA.md and define taxonomy tags explicitly.",
                    "Add/confirm entity classes (Person, Organization, Model, etc.).",
                ],
            }
        )

    if not checks.get("crosslink_marker_present") or not checks.get("schema_crosslink_section_present"):
        steps.append(
            {
                "id": "repair-crosslinks",
                "title": "Add crosslink conventions",
                "reason": "Crosslink markers/section absent in schema or pages.",
                "actions": [
                    "Add a Crosslinking section to SCHEMA.md.",
                    "Add wikilinks ([[Entity Name]]) between index and key pages.",
                ],
            }
        )

    orphan_pages = checks.get("orphan_pages", []) or []
    if orphan_pages:
        preview = orphan_pages[:12]
        steps.append(
            {
                "id": "repair-orphans",
                "title": "Resolve orphan pages",
                "reason": f"Detected {len(orphan_pages)} pages with zero inbound links.",
                "actions": [
                    "Link each orphan from index.md or a topic hub page.",
                    "Ensure each orphan has at least one inbound [[wikilink]].",
                ],
                "orphan_preview": preview,
            }
        )

    frontmatter_ratio = float(checks.get("frontmatter_ratio") or 0)
    if frontmatter_ratio < 0.5:
        steps.append(
            {
                "id": "repair-frontmatter",
                "title": "Increase frontmatter coverage",
                "reason": f"Frontmatter ratio is {frontmatter_ratio:.2f} (< 0.50).",
                "actions": [
                    "Add YAML frontmatter blocks to high-value markdown pages.",
                    "Include at minimum: title, tags, updated_at.",
                ],
            }
        )

    if checks.get("graph_drift_detected"):
        steps.append(
            {
                "id": "repair-graph-drift",
                "title": "Reduce graph drift",
                "reason": "Link density/orphan ratio indicates a fragmented knowledge graph.",
                "actions": [
                    "Create or update hub pages by topic.",
                    "Add reciprocal links between related entities/concepts.",
                ],
            }
        )

    return {
        "wiki_id": lint.get("wiki_id"),
        "subject": lint.get("subject"),
        "health": lint.get("health"),
        "score": lint.get("score"),
        "playbook": steps,
        "lint": lint,
    }


def _build_repair_report(username: str, wiki_id: int, before: dict, after: dict, scaffold: dict, playbook: dict) -> dict:
    before_missing_files = before.get("missing", {}).get("files", [])
    before_missing_dirs = before.get("missing", {}).get("dirs", [])
    after_missing_files = after.get("missing", {}).get("files", [])
    after_missing_dirs = after.get("missing", {}).get("dirs", [])

    before_orphans = before.get("checks", {}).get("orphan_pages", []) or []
    after_orphans = after.get("checks", {}).get("orphan_pages", []) or []

    resolved_issues: list[str] = []
    unresolved_issues: list[str] = []

    if len(after_missing_files) < len(before_missing_files):
        resolved_issues.append("Reduced missing required files.")
    if len(after_missing_dirs) < len(before_missing_dirs):
        resolved_issues.append("Reduced missing required directories.")
    if (after.get("score") or 0) > (before.get("score") or 0):
        resolved_issues.append("Improved lint score.")

    if after_missing_files:
        unresolved_issues.append(f"Missing files remain: {', '.join(after_missing_files)}")
    if after_missing_dirs:
        unresolved_issues.append(f"Missing directories remain: {', '.join(after_missing_dirs)}")
    if after_orphans:
        unresolved_issues.append(f"Orphan pages remain: {len(after_orphans)}")
    if after.get("checks", {}).get("graph_drift_detected"):
        unresolved_issues.append("Graph drift still detected.")
    if not after.get("checks", {}).get("taxonomy_markers_present"):
        unresolved_issues.append("Taxonomy markers still missing in schema.")

    recommendations = []
    for step in (playbook.get("playbook") or []):
        recommendations.append(f"{step.get('title')}: {step.get('reason')}")
        if len(recommendations) >= 3:
            break

    summary = {
        "score_delta": (after.get("score") or 0) - (before.get("score") or 0),
        "health_before": before.get("health"),
        "health_after": after.get("health"),
        "created_scaffold": scaffold.get("created", []),
        "skipped_scaffold": scaffold.get("skipped", []),
    }

    return {
        "wiki_id": wiki_id,
        "subject": before.get("subject") or after.get("subject"),
        "summary": summary,
        "resolved_issues": resolved_issues,
        "unresolved_issues": unresolved_issues,
        "next_3_recommendations": recommendations,
    }


def _render_repair_report_markdown(report: dict) -> str:
    subject = report.get("subject") or "Unknown Wiki"
    summary = report.get("summary") or {}
    resolved = report.get("resolved_issues") or []
    unresolved = report.get("unresolved_issues") or []
    next_three = report.get("next_3_recommendations") or []
    created = summary.get("created_scaffold") or []
    skipped = summary.get("skipped_scaffold") or []

    lines = [
        f"# Repair Report — {subject}",
        "",
        f"- Generated: {datetime.now(timezone.utc).isoformat()}",
        f"- Wiki ID: {report.get('wiki_id')}",
        f"- Health: {summary.get('health_before')} → {summary.get('health_after')}",
        f"- Score delta: {summary.get('score_delta')}",
        "",
        "## Scaffold changes",
        f"- Created: {', '.join(created) if created else 'none'}",
        f"- Skipped: {', '.join(skipped) if skipped else 'none'}",
        "",
        "## Resolved issues",
    ]
    if resolved:
        lines.extend([f"- {item}" for item in resolved])
    else:
        lines.append("- none")

    lines.extend(["", "## Unresolved issues"])
    if unresolved:
        lines.extend([f"- {item}" for item in unresolved])
    else:
        lines.append("- none")

    lines.extend(["", "## Next 3 recommendations"])
    if next_three:
        lines.extend([f"1. {item}" for item in next_three])
    else:
        lines.append("1. none")

    return "\n".join(lines).strip() + "\n"


def _repair_reports_dir_for_wiki(wiki: dict) -> Path:
    wiki_path = _resolve_wiki_path(wiki)
    return wiki_path / "reports" / "repair-reports"


def _export_repair_report(username: str, wiki_id: int, persist: bool = True) -> dict:
    wiki = _find_wiki(username, wiki_id)
    before = _lint_wiki(username, wiki_id)
    scaffold = {"created": [], "skipped": []}
    after = _lint_wiki(username, wiki_id)
    playbook = _build_conformance_playbook(username, wiki_id)
    report = _build_repair_report(username, wiki_id, before, after, scaffold, playbook)
    markdown = _render_repair_report_markdown(report)

    subject_slug = re.sub(r"[^a-z0-9]+", "-", str(wiki.get("subject", "wiki")).lower()).strip("-") or "wiki"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = f"{subject_slug}-repair-report-{stamp}.md"

    saved_path = None
    if persist:
        reports_dir = _repair_reports_dir_for_wiki(wiki)
        reports_dir.mkdir(parents=True, exist_ok=True)
        out_path = reports_dir / filename
        out_path.write_text(markdown, encoding="utf-8")
        saved_path = str(out_path)

        log_path = _resolve_wiki_path(wiki) / "log.md"
        if log_path.exists():
            stamp_human = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(f"- {stamp_human}: repair report exported ({filename})\n")

        _add_timeline_event(
            username,
            "wiki",
            f"Repair report exported: {wiki.get('subject', 'Unknown Wiki')}",
            {"wiki_id": wiki_id, "filename": filename, "saved_path": saved_path},
        )

    return {
        "wiki_id": wiki_id,
        "subject": report.get("subject"),
        "filename": filename,
        "persisted": bool(persist),
        "saved_path": saved_path,
        "markdown": markdown,
        "report": report,
    }


def _list_repair_report_artifacts(username: str, wiki_id: int, limit: int = 30) -> dict:
    wiki = _find_wiki(username, wiki_id)
    reports_dir = _repair_reports_dir_for_wiki(wiki)
    if not reports_dir.exists():
        return {"wiki_id": wiki_id, "subject": wiki.get("subject"), "items": []}

    items: list[dict] = []
    for p in reports_dir.glob("*.md"):
        stat = p.stat()
        items.append({
            "filename": p.name,
            "path": str(p),
            "size_bytes": stat.st_size,
            "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        })

    items.sort(key=lambda i: i.get("modified_at", ""), reverse=True)
    return {
        "wiki_id": wiki_id,
        "subject": wiki.get("subject"),
        "items": items[: max(1, min(int(limit), 100))],
    }


def _read_repair_report_artifact(username: str, wiki_id: int, filename: str) -> dict:
    wiki = _find_wiki(username, wiki_id)
    safe = Path(filename).name
    if not safe.endswith(".md"):
        raise HTTPException(status_code=400, detail="Only markdown artifacts are supported")
    path = _repair_reports_dir_for_wiki(wiki) / safe
    if not path.exists():
        raise HTTPException(status_code=404, detail="Artifact not found")
    text = path.read_text(encoding="utf-8")
    return {
        "wiki_id": wiki_id,
        "subject": wiki.get("subject"),
        "filename": safe,
        "path": str(path),
        "markdown": text,
    }


def _run_guided_repair(username: str, wiki_id: int, payload: WikiRepairRunPayload) -> dict:
    _require_admin(username)
    before = _lint_wiki(username, wiki_id)
    scaffold = _create_missing_scaffold(username, wiki_id, WikiScaffoldPayload(targets=[]))
    after = scaffold.get("lint") or _lint_wiki(username, wiki_id)
    playbook = _build_conformance_playbook(username, wiki_id)
    report = _build_repair_report(username, wiki_id, before, after, scaffold, playbook)
    _add_timeline_event(
        username,
        "wiki",
        f"Guided repair run: {playbook.get('subject', 'Unknown Wiki')}",
        {
            "wiki_id": wiki_id,
            "before_score": before.get("score"),
            "after_score": after.get("score"),
            "created": scaffold.get("created", []),
        },
    )
    return {
        "wiki_id": wiki_id,
        "subject": playbook.get("subject"),
        "before": before,
        "after": after,
        "scaffold": {"created": scaffold.get("created", []), "skipped": scaffold.get("skipped", [])},
        "playbook": playbook.get("playbook", []),
        "report": report,
        "include_orphan_fix_guidance": bool(payload.include_orphan_fix_guidance),
    }


def _create_missing_scaffold(username: str, wiki_id: int, payload: WikiScaffoldPayload) -> dict:
    _require_admin(username)
    wiki = _find_wiki(username, wiki_id)
    wiki_path = _resolve_wiki_path(wiki)
    lint = _lint_wiki(username, wiki_id)

    requested = [str(t).strip().strip("/") for t in (payload.targets or []) if str(t).strip()]
    to_create = requested if requested else [*lint.get("missing", {}).get("files", []), *lint.get("missing", {}).get("dirs", [])]

    created: list[str] = []
    skipped: list[str] = []
    allowed_files = {"SCHEMA.md", "index.md", "log.md", "setup-interview.md"}
    allowed_dirs = {"raw/articles", "raw/papers", "raw/transcripts", "raw/assets"}

    for rel in to_create:
        if rel in allowed_dirs:
            p = wiki_path / rel
            p.mkdir(parents=True, exist_ok=True)
            created.append(rel)
            continue
        if rel in allowed_files:
            p = wiki_path / rel
            if p.exists():
                skipped.append(rel)
                continue
            p.parent.mkdir(parents=True, exist_ok=True)
            subject = str(wiki.get("subject", "Unknown Wiki"))
            if rel == "SCHEMA.md":
                text = (
                    f"# SCHEMA — {subject}\n\n"
                    "## Taxonomy\n"
                    "- tag:\n\n"
                    "## Entity types\n"
                    "- Person\n- Organization\n- Model\n\n"
                    "## Crosslinking\n"
                    "- Use wikilinks like [[Entity Name]].\n"
                )
            elif rel == "index.md":
                text = f"# {subject}\n\n## Overview\n- Seed this index with key nodes and links.\n"
            elif rel == "log.md":
                text = f"# Wiki Log — {subject}\n\n## Events\n- Scaffold created.\n"
            else:
                text = (
                    f"# Wiki Charter & Intake Notes — {subject}\n\n"
                    "_Status: pending_\n\n"
                    "## Schema-driving intake\n- Domain scope:\n- Taxonomy tags:\n- Seed entities:\n"
                )
            p.write_text(text, encoding="utf-8")
            created.append(rel)
            continue
        skipped.append(rel)

    _add_timeline_event(
        username,
        "wiki",
        f"Wiki scaffold created: {wiki.get('subject', 'Unknown Wiki')}",
        {"wiki_id": wiki_id, "created": created, "skipped": skipped},
    )
    post_lint = _lint_wiki(username, wiki_id)
    return {
        "wiki_id": wiki_id,
        "subject": wiki.get("subject", ""),
        "created": created,
        "skipped": skipped,
        "lint": post_lint,
    }


def _load_wiki_doc(doc_kind: str) -> dict:
    normalized = doc_kind.strip().lower()
    mapping = {
        "help": Path("docs/LLM_WIKI_TAB_HELP.md"),
        "summary": Path("docs/LLM_WIKI_TAB_ONE_PAGE_SUMMARY.md"),
    }
    path = mapping.get(normalized)
    if path is None:
        raise HTTPException(status_code=404, detail="Unknown doc kind")
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Doc not found: {path}")
    return {"kind": normalized, "path": str(path.resolve()), "content": path.read_text(encoding="utf-8")}


def _resolve_schema_path(wiki: dict) -> Path:
    wiki_path = _resolve_wiki_path(wiki)
    return wiki_path / "SCHEMA.md"


def _get_wiki_schema(username: str, wiki_id: int) -> dict:
    wiki = _find_wiki(username, wiki_id)
    path = _resolve_schema_path(wiki)
    if not path.exists():
        subject = str(wiki.get("subject", "Unknown Wiki"))
        seed = (
            f"# SCHEMA — {subject}\n\n"
            "## Taxonomy\n"
            "- tag:\n\n"
            "## Entity types\n"
            "- Person\n"
            "- Organization\n"
            "- Model\n\n"
            "## Crosslinking\n"
            "- Use wikilinks like [[Entity Name]].\n"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(seed, encoding="utf-8")
    return {
        "wiki_id": int(wiki.get("id", wiki_id)),
        "subject": str(wiki.get("subject", "")),
        "schema_path": str(path),
        "content": path.read_text(encoding="utf-8"),
    }


def _put_wiki_schema(username: str, wiki_id: int, payload: WikiSchemaPayload) -> dict:
    _require_admin(username)
    wiki = _find_wiki(username, wiki_id)
    path = _resolve_schema_path(wiki)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload.content, encoding="utf-8")
    _add_timeline_event(
        username,
        "wiki",
        f"Schema updated: {wiki.get('subject', 'Unknown Wiki')}",
        {"wiki_id": wiki_id, "schema_path": str(path)},
    )
    return {
        "wiki_id": int(wiki.get("id", wiki_id)),
        "subject": str(wiki.get("subject", "")),
        "schema_path": str(path),
        "updated": True,
    }


def _get_wiki_interview(username: str, wiki_id: int) -> dict:
    wiki = _find_wiki(username, wiki_id)
    path = _resolve_interview_path(wiki)
    if not path.exists():
        subject = str(wiki.get("subject", "Unknown Wiki"))
        created_iso = datetime.now(timezone.utc).isoformat()
        seed = (
            f"# Wiki Charter & Intake Notes — {subject}\n\n"
            f"_Status: pending_\n\n"
            "This file captures schema-driving intake and post-init charter notes.\n\n"
            "## Schema-driving intake\n"
            "- Domain scope:\n"
            "- Out of scope:\n"
            "- Taxonomy tags:\n"
            "- Seed entities:\n"
            "- Seed concepts:\n"
            "- Seed sources:\n\n"
            "## Follow-up charter notes\n"
            "-\n\n"
            f"Created at: {created_iso}\n"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(seed, encoding="utf-8")
        wiki["interview_status"] = "pending"
        wiki["interview_path"] = str(path)
    return {
        "wiki_id": int(wiki.get("id", wiki_id)),
        "subject": str(wiki.get("subject", "")),
        "status": str(wiki.get("interview_status", "pending")),
        "interview_path": str(path),
        "content": path.read_text(encoding="utf-8"),
    }


def _update_wiki_interview(username: str, wiki_id: int, payload: WikiInterviewPayload) -> dict:
    _require_admin(username)
    wiki = _find_wiki(username, wiki_id)
    path = _resolve_interview_path(wiki)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload.content, encoding="utf-8")
    wiki["interview_status"] = payload.status
    wiki["interview_path"] = str(path)
    _add_timeline_event(
        username,
        "wiki",
        f"Charter notes updated: {wiki.get('subject', 'Unknown Wiki')}",
        {"wiki_id": wiki_id, "interview_status": payload.status},
    )
    return {
        "wiki_id": int(wiki.get("id", wiki_id)),
        "status": payload.status,
        "interview_path": str(path),
        "updated": True,
    }


def _validate_wiki_blueprint(payload: WikiBlueprintPayload) -> dict:
    slug = _slugify(payload.wiki_slug)
    wiki_dir = _resolve_wiki_dir(payload.wiki_root_path, slug)
    scope_ok = len(payload.scope.strip()) >= 20
    taxonomy_ok = len(_normalize_seed_list(payload.taxonomy_tags, max_items=40)) >= 5
    readiness_score = 0
    readiness_score += 25 if payload.subject.strip() else 0
    readiness_score += 25 if scope_ok else 0
    readiness_score += 25 if taxonomy_ok else 0
    readiness_score += 25 if len(_normalize_seed_list(payload.seed_entities, max_items=30)) >= 3 else 0
    if readiness_score >= 85:
        readiness = "green"
    elif readiness_score >= 60:
        readiness = "yellow"
    else:
        readiness = "red"

    checks = {
        "scope_defined": scope_ok,
        "taxonomy_present": taxonomy_ok,
        "index_and_log_planned": True,
        "crosslink_rule_defined": True,
        "under_allowed_root": str(wiki_dir.resolve()).startswith(str(WIKI_ROOT_PATH.resolve())),
    }

    return {
        "wiki_slug": slug,
        "wiki_path": str(wiki_dir),
        "path_exists": wiki_dir.exists(),
        "readiness": readiness,
        "readiness_score": readiness_score,
        "checks": checks,
    }


def _create_wiki_from_blueprint(username: str, payload: WikiBlueprintPayload) -> dict:
    _require_admin(username)
    state = _ensure_operator_state(username)
    next_id = max((int(item.get("id", 0)) for item in state["llm_wikis"]), default=0) + 1

    bootstrap = _init_karpathy_wiki_from_blueprint(**payload.model_dump())
    item = {
        "id": next_id,
        "subject": payload.subject.strip(),
        "status": payload.status,
        "health": payload.health,
        "last_indexed_at": datetime.now(timezone.utc).isoformat(),
        "notes": payload.notes.strip() or f"Scope: {payload.scope.strip()[:120]}",
        **bootstrap,
    }
    state["llm_wikis"].insert(0, item)
    del state["llm_wikis"][50:]
    _add_timeline_event(
        username,
        "wiki",
        f"Wiki initialized via wizard: {item['subject']}",
        {"wiki_id": item["id"], "wiki_path": item["wiki_path"], "slug": item["wiki_slug"]},
    )
    return item


def _run_voice_command(username: str, transcript_text: str) -> dict:
    state = _ensure_operator_state(username)
    normalized = transcript_text.strip()
    lowered = normalized.lower()

    if "dashboard" in lowered:
        action = "open_dashboard"
        result = "Dashboard context refreshed"
    elif "prompt" in lowered:
        action = "show_prompt_history"
        result = "Prompt history surfaced"
    elif "voice" in lowered:
        action = "switch_voice_profile"
        result = "Voice profile switched to low-latency"
    else:
        action = "generic_command"
        result = f"Command captured: {normalized[:80]}"

    entry = {
        "id": next(voice_id_counter),
        "transcript": normalized,
        "action": action,
        "result": result,
        "status": "success",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    state["voice_events"].insert(0, entry)
    del state["voice_events"][20:]
    _add_timeline_event(
        username,
        "voice",
        f"Voice command #{entry['id']} handled ({action})",
        {"transcript": normalized[:80], "result": result},
    )
    return entry


@app.post("/api/auth/login")
def login(payload: LoginPayload):
    operators = _load_operators()
    match = next(
        (
            op
            for op in operators
            if op.get("username") == payload.username and op.get("pin") == payload.pin
        ),
        None,
    )
    if not match:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token, session = _create_session(payload.username)
    _ensure_operator_state(payload.username)
    return {
        "token": token,
        "username": payload.username,
        "role": _get_operator_role(payload.username),
        "session_idle_timeout_seconds": SESSION_IDLE_TIMEOUT_SECONDS,
        "session_absolute_timeout_seconds": SESSION_ABSOLUTE_TIMEOUT_SECONDS,
        "session_expires_at": _expires_at_iso(float(session["last_seen_ts"])),
        "session_absolute_expires_at": _absolute_expires_at_iso(float(session["created_ts"])),
        "session_last_seen_at": _ts_iso(float(session["last_seen_ts"])),
    }


@app.get("/api/auth/me")
def me(x_session_token: str | None = Header(default=None)):
    username = _require_operator(x_session_token)
    session = sessions.get(x_session_token or "")
    if not session:
        raise HTTPException(status_code=401, detail="Invalid session token")

    last_seen_ts = float(session["last_seen_ts"])
    created_ts = float(session.get("created_ts", last_seen_ts))
    return {
        "username": username,
        "role": _get_operator_role(username),
        "session_idle_timeout_seconds": SESSION_IDLE_TIMEOUT_SECONDS,
        "session_absolute_timeout_seconds": SESSION_ABSOLUTE_TIMEOUT_SECONDS,
        "session_expires_at": _expires_at_iso(last_seen_ts),
        "session_absolute_expires_at": _absolute_expires_at_iso(created_ts),
        "session_last_seen_at": _ts_iso(last_seen_ts),
    }


@app.post("/api/auth/logout")
def logout(x_session_token: str | None = Header(default=None)):
    if not x_session_token:
        raise HTTPException(status_code=401, detail="Missing session token")
    _revoke_session(x_session_token)
    return {"ok": True}


@app.get("/api/health")
def health():
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


@app.get("/api/metrics")
def metrics(x_session_token: str | None = Header(default=None)):
    username = _require_operator(x_session_token)
    payload = {
        "agent_status": "Online",
        "tasks_running": randint(1, 6),
        "avg_response_seconds": round(uniform(0.7, 1.8), 2),
        "error_rate_percent": round(uniform(0.1, 0.7), 2),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "operator": username,
    }
    _add_timeline_event(
        username,
        "metric",
        "Dashboard metrics refreshed",
        {
            "tasks_running": payload["tasks_running"],
            "avg_response_seconds": payload["avg_response_seconds"],
            "error_rate_percent": payload["error_rate_percent"],
        },
    )
    alerts = _refresh_alerts(username, payload)
    top_alert = alerts[0] if alerts else None
    if top_alert:
        _add_timeline_event(
            username,
            "alert",
            f"Alert state: {top_alert['severity']} · {top_alert['message']}",
            {"code": top_alert["code"], "severity": top_alert["severity"]},
        )
    return payload


@app.post("/api/prompts")
def submit_prompt(payload: PromptRequest, x_session_token: str | None = Header(default=None)):
    username = _require_operator(x_session_token)
    return _run_prompt(username, payload.prompt.strip())


@app.get("/api/prompts")
def get_prompt_history(limit: int = 10, x_session_token: str | None = Header(default=None)):
    username = _require_operator(x_session_token)
    state = _ensure_operator_state(username)
    safe_limit = max(1, min(limit, 20))
    return {"items": state["prompt_history"][:safe_limit]}


@app.get("/api/prompt-templates")
def get_prompt_templates(limit: int = 25, x_session_token: str | None = Header(default=None)):
    username = _require_operator(x_session_token)
    state = _ensure_operator_state(username)
    safe_limit = max(1, min(limit, 25))
    return {"items": state["prompt_templates"][:safe_limit]}


@app.post("/api/prompt-templates")
def create_prompt_template(
    payload: PromptTemplatePayload, x_session_token: str | None = Header(default=None)
):
    username = _require_operator(x_session_token)
    return _create_prompt_template(username, payload.name, payload.prompt)


@app.delete("/api/prompt-templates/{template_id}")
def delete_prompt_template(template_id: int, x_session_token: str | None = Header(default=None)):
    username = _require_operator(x_session_token)
    _delete_prompt_template(username, template_id)
    return {"ok": True}


@app.post("/api/voice/command")
def submit_voice_command(
    payload: VoiceCommandRequest, x_session_token: str | None = Header(default=None)
):
    username = _require_operator(x_session_token)
    return _run_voice_command(username, payload.transcript.strip())


@app.get("/api/voice/events")
def get_voice_events(limit: int = 10, x_session_token: str | None = Header(default=None)):
    username = _require_operator(x_session_token)
    state = _ensure_operator_state(username)
    safe_limit = max(1, min(limit, 20))
    return {"items": state["voice_events"][:safe_limit]}


@app.get("/api/timeline")
def get_timeline(
    limit: int = 20, kind: str = "all", x_session_token: str | None = Header(default=None)
):
    username = _require_operator(x_session_token)
    state = _ensure_operator_state(username)
    safe_limit = max(1, min(limit, 50))
    if kind == "all":
        items = state["timeline"][:safe_limit]
    else:
        items = [item for item in state["timeline"] if item["kind"] == kind][:safe_limit]
    return {"items": items}


@app.get("/api/alerts")
def get_alerts(limit: int = 5, x_session_token: str | None = Header(default=None)):
    username = _require_operator(x_session_token)
    state = _ensure_operator_state(username)
    safe_limit = max(1, min(limit, 10))
    return {"items": state["alerts"][:safe_limit]}


@app.post("/api/alerts/{alert_id}/action")
def alert_action(
    alert_id: int,
    payload: AlertActionPayload,
    x_session_token: str | None = Header(default=None),
):
    username = _require_operator(x_session_token)
    return _apply_alert_action(username, alert_id, payload.action)


@app.get("/api/settings")
def get_settings(x_session_token: str | None = Header(default=None)):
    username = _require_operator(x_session_token)
    state = _ensure_operator_state(username)
    return state["settings"]


@app.put("/api/settings")
def put_settings(payload: SettingsPayload, x_session_token: str | None = Header(default=None)):
    username = _require_operator(x_session_token)
    _require_admin(username)
    state = _ensure_operator_state(username)
    data = payload.model_dump()
    state["settings"] = data
    _save_global_settings(data)
    _add_timeline_event(username, "settings", "Settings updated", data)
    return data


@app.get("/api/llm-wikis")
def get_llm_wikis(limit: int = 20, x_session_token: str | None = Header(default=None)):
    username = _require_operator(x_session_token)
    return {"items": _list_llm_wikis(username, limit)}


@app.post("/api/llm-wikis/validate-blueprint")
def validate_llm_wiki_blueprint(payload: WikiBlueprintPayload, x_session_token: str | None = Header(default=None)):
    _require_operator(x_session_token)
    return _validate_wiki_blueprint(payload)


@app.post("/api/llm-wikis/init")
def init_llm_wiki_blueprint(payload: WikiBlueprintPayload, x_session_token: str | None = Header(default=None)):
    username = _require_operator(x_session_token)
    return _create_wiki_from_blueprint(username, payload)


@app.post("/api/llm-wikis")
def create_llm_wiki(payload: LlmWikiPayload, x_session_token: str | None = Header(default=None)):
    username = _require_operator(x_session_token)
    return _create_llm_wiki(username, payload)


@app.put("/api/llm-wikis/{wiki_id}")
def update_llm_wiki(wiki_id: int, payload: LlmWikiPayload, x_session_token: str | None = Header(default=None)):
    username = _require_operator(x_session_token)
    return _update_llm_wiki(username, wiki_id, payload)


@app.get("/api/llm-wikis/{wiki_id}/interview")
def get_wiki_interview(wiki_id: int, x_session_token: str | None = Header(default=None)):
    username = _require_operator(x_session_token)
    return _get_wiki_interview(username, wiki_id)


@app.get("/api/llm-wikis/{wiki_id}/schema")
def get_wiki_schema(wiki_id: int, x_session_token: str | None = Header(default=None)):
    username = _require_operator(x_session_token)
    return _get_wiki_schema(username, wiki_id)


@app.put("/api/llm-wikis/{wiki_id}/schema")
def put_wiki_schema(
    wiki_id: int,
    payload: WikiSchemaPayload,
    x_session_token: str | None = Header(default=None),
):
    username = _require_operator(x_session_token)
    return _put_wiki_schema(username, wiki_id, payload)


@app.put("/api/llm-wikis/{wiki_id}/interview")
def put_wiki_interview(
    wiki_id: int,
    payload: WikiInterviewPayload,
    x_session_token: str | None = Header(default=None),
):
    username = _require_operator(x_session_token)
    return _update_wiki_interview(username, wiki_id, payload)


@app.post("/api/llm-wikis/{wiki_id}/ingest")
def ingest_wiki_source(
    wiki_id: int,
    payload: WikiIngestPayload,
    x_session_token: str | None = Header(default=None),
):
    username = _require_operator(x_session_token)
    return _ingest_wiki_source(username, wiki_id, payload)


@app.post("/api/llm-wikis/{wiki_id}/ask")
def ask_wiki(
    wiki_id: int,
    payload: WikiAskPayload,
    x_session_token: str | None = Header(default=None),
):
    username = _require_operator(x_session_token)
    return _ask_wiki(username, wiki_id, payload)


@app.get("/api/llm-wikis/{wiki_id}/lint")
def lint_wiki(wiki_id: int, x_session_token: str | None = Header(default=None)):
    username = _require_operator(x_session_token)
    return _lint_wiki(username, wiki_id)


@app.post("/api/llm-wikis/{wiki_id}/scaffold")
def scaffold_wiki(
    wiki_id: int,
    payload: WikiScaffoldPayload,
    x_session_token: str | None = Header(default=None),
):
    username = _require_operator(x_session_token)
    return _create_missing_scaffold(username, wiki_id, payload)


@app.get("/api/llm-wikis/{wiki_id}/lint/history")
def wiki_lint_history(
    wiki_id: int,
    limit: int = 20,
    x_session_token: str | None = Header(default=None),
):
    username = _require_operator(x_session_token)
    return _get_wiki_lint_history(username, wiki_id, limit)


@app.get("/api/llm-wikis/{wiki_id}/lint/playbook")
def wiki_lint_playbook(wiki_id: int, x_session_token: str | None = Header(default=None)):
    username = _require_operator(x_session_token)
    return _build_conformance_playbook(username, wiki_id)


@app.post("/api/llm-wikis/{wiki_id}/lint/repair-run")
def wiki_lint_repair_run(
    wiki_id: int,
    payload: WikiRepairRunPayload,
    x_session_token: str | None = Header(default=None),
):
    username = _require_operator(x_session_token)
    return _run_guided_repair(username, wiki_id, payload)


@app.get("/api/llm-wikis/{wiki_id}/lint/repair-report")
def wiki_lint_repair_report(wiki_id: int, x_session_token: str | None = Header(default=None)):
    username = _require_operator(x_session_token)
    before = _lint_wiki(username, wiki_id)
    scaffold = {"created": [], "skipped": []}
    after = _lint_wiki(username, wiki_id)
    playbook = _build_conformance_playbook(username, wiki_id)
    return _build_repair_report(username, wiki_id, before, after, scaffold, playbook)


@app.get("/api/llm-wikis/{wiki_id}/lint/repair-report/export")
def wiki_lint_repair_report_export(
    wiki_id: int,
    persist: bool = True,
    x_session_token: str | None = Header(default=None),
):
    username = _require_operator(x_session_token)
    return _export_repair_report(username, wiki_id, persist=persist)


@app.get("/api/llm-wikis/{wiki_id}/lint/repair-report/artifacts")
def wiki_lint_repair_report_artifacts(
    wiki_id: int,
    limit: int = 30,
    x_session_token: str | None = Header(default=None),
):
    username = _require_operator(x_session_token)
    return _list_repair_report_artifacts(username, wiki_id, limit=limit)


@app.get("/api/llm-wikis/{wiki_id}/lint/repair-report/artifacts/{filename}")
def wiki_lint_repair_report_artifact_read(
    wiki_id: int,
    filename: str,
    x_session_token: str | None = Header(default=None),
):
    username = _require_operator(x_session_token)
    return _read_repair_report_artifact(username, wiki_id, filename)


@app.get("/api/llm-wikis/docs/{doc_kind}")
def get_wiki_doc(doc_kind: str, x_session_token: str | None = Header(default=None)):
    _require_operator(x_session_token)
    return _load_wiki_doc(doc_kind)


app.mount("/", StaticFiles(directory=".", html=True), name="static")
