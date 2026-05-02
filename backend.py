from datetime import datetime, timezone
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


def _init_karpathy_wiki_structure(subject: str) -> dict:
    slug = _slugify(subject)
    wiki_dir = WIKI_ROOT_PATH / slug
    created_at = datetime.now(timezone.utc)
    created_iso = created_at.isoformat()
    created_day = created_at.date().isoformat()

    (wiki_dir / "raw" / "articles").mkdir(parents=True, exist_ok=True)
    (wiki_dir / "raw" / "papers").mkdir(parents=True, exist_ok=True)
    (wiki_dir / "raw" / "transcripts").mkdir(parents=True, exist_ok=True)
    (wiki_dir / "raw" / "assets").mkdir(parents=True, exist_ok=True)
    (wiki_dir / "entities").mkdir(parents=True, exist_ok=True)
    (wiki_dir / "concepts").mkdir(parents=True, exist_ok=True)
    (wiki_dir / "comparisons").mkdir(parents=True, exist_ok=True)
    (wiki_dir / "queries").mkdir(parents=True, exist_ok=True)

    schema = f"""# Wiki Schema\n\n## Domain\n{subject}\n\n## Conventions\n- File names: lowercase-kebab-case\n- Every page uses YAML frontmatter\n- Use [[wikilinks]] for cross-references\n- Log all changes in log.md\n\n## Frontmatter\n```yaml\n---\ntitle: Page Title\ncreated: YYYY-MM-DD\nupdated: YYYY-MM-DD\ntype: entity | concept | comparison | query | summary\ntags: []\nsources: []\n---\n```\n\n## Tag Taxonomy\n- model\n- architecture\n- dataset\n- benchmark\n- company\n- person\n- technique\n- comparison\n- timeline\n- open-question\n"""

    index_md = f"""# Wiki Index\n\n> Last updated: {created_day} | Total pages: 0\n\n## Entities\n\n## Concepts\n\n## Comparisons\n\n## Queries\n"""

    log_md = f"""# Wiki Log\n\n## [{created_day}] create | Wiki initialized\n- Subject: {subject}\n- Process: karpathy-llm-wiki bootstrap\n- Root: {wiki_dir}\n"""

    interview_md = f"""# Setup Interview — {subject}\n\n_Status: pending_\n\nPlease answer these before first ingestion:\n\n1. What is the exact domain scope for this wiki?\n2. What are the top 5 entities that must exist first?\n3. What sources should be ingested first (URLs/files)?\n4. What tag taxonomy additions do you want beyond defaults?\n5. What quality bar should trigger "complete" status for this wiki?\n\nCreated at: {created_iso}\n"""

    (wiki_dir / "SCHEMA.md").write_text(schema, encoding="utf-8")
    (wiki_dir / "index.md").write_text(index_md, encoding="utf-8")
    (wiki_dir / "log.md").write_text(log_md, encoding="utf-8")
    interview_path = wiki_dir / "setup-interview.md"
    interview_path.write_text(interview_md, encoding="utf-8")

    return {
        "wiki_slug": slug,
        "wiki_path": str(wiki_dir),
        "interview_path": str(interview_path),
        "interview_status": "pending",
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


def _list_llm_wikis(username: str, limit: int) -> list[dict]:
    state = _ensure_operator_state(username)
    _ensure_existing_wiki_tiles(state)
    safe_limit = max(1, min(limit, 50))
    return state["llm_wikis"][:safe_limit]


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
        f"Wiki created: {item['subject']} (Karpathy gist init + setup interview)",
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


def _get_wiki_interview(username: str, wiki_id: int) -> dict:
    wiki = _find_wiki(username, wiki_id)
    path = _resolve_interview_path(wiki)
    if not path.exists():
        subject = str(wiki.get("subject", "Unknown Wiki"))
        created_iso = datetime.now(timezone.utc).isoformat()
        seed = (
            f"# Setup Interview — {subject}\n\n"
            f"_Status: pending_\n\n"
            "Please answer these before first ingestion:\n\n"
            "1. What is the exact domain scope for this wiki?\n"
            "2. What are the top 5 entities that must exist first?\n"
            "3. What sources should be ingested first (URLs/files)?\n"
            "4. What tag taxonomy additions do you want beyond defaults?\n"
            "5. What quality bar should trigger \"complete\" status for this wiki?\n\n"
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
        f"Setup interview updated: {wiki.get('subject', 'Unknown Wiki')}",
        {"wiki_id": wiki_id, "interview_status": payload.status},
    )
    return {
        "wiki_id": int(wiki.get("id", wiki_id)),
        "status": payload.status,
        "interview_path": str(path),
        "updated": True,
    }


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


@app.put("/api/llm-wikis/{wiki_id}/interview")
def put_wiki_interview(
    wiki_id: int,
    payload: WikiInterviewPayload,
    x_session_token: str | None = Header(default=None),
):
    username = _require_operator(x_session_token)
    return _update_wiki_interview(username, wiki_id, payload)


app.mount("/", StaticFiles(directory=".", html=True), name="static")
