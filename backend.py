from datetime import datetime, timezone
from itertools import count
from pathlib import Path
from random import randint, uniform
import json
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
        {"username": "admin", "pin": "1234"},
        {"username": "ops", "pin": "1111"},
    ]
}

sessions: dict[str, str] = {}
prompt_id_counter = count(1)
voice_id_counter = count(1)
timeline_id_counter = count(1)
alert_id_counter = count(1)

operator_state: dict[str, dict] = {}


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


def _ensure_operator_state(username: str) -> dict:
    if username not in operator_state:
        operator_state[username] = {
            "prompt_history": [],
            "voice_events": [],
            "timeline": [],
            "alerts": [],
            "settings": _load_global_settings(),
        }
    return operator_state[username]


def _require_operator(x_session_token: str | None) -> str:
    if not x_session_token:
        raise HTTPException(status_code=401, detail="Missing session token")
    username = sessions.get(x_session_token)
    if not username:
        raise HTTPException(status_code=401, detail="Invalid session token")
    _ensure_operator_state(username)
    return username


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
    for alert in state["alerts"]:
        if alert["code"] == code:
            alert.update(
                {
                    "severity": severity,
                    "message": message,
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

    del state["alerts"][10:]
    return state["alerts"]


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

    token = secrets.token_urlsafe(24)
    sessions[token] = payload.username
    _ensure_operator_state(payload.username)
    return {"token": token, "username": payload.username}


@app.get("/api/auth/me")
def me(x_session_token: str | None = Header(default=None)):
    username = _require_operator(x_session_token)
    return {"username": username}


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


@app.get("/api/settings")
def get_settings(x_session_token: str | None = Header(default=None)):
    username = _require_operator(x_session_token)
    state = _ensure_operator_state(username)
    return state["settings"]


@app.put("/api/settings")
def put_settings(payload: SettingsPayload, x_session_token: str | None = Header(default=None)):
    username = _require_operator(x_session_token)
    state = _ensure_operator_state(username)
    data = payload.model_dump()
    state["settings"] = data
    _save_global_settings(data)
    _add_timeline_event(username, "settings", "Settings updated", data)
    return data


app.mount("/", StaticFiles(directory=".", html=True), name="static")
