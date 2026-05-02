#!/usr/bin/env python3
"""Run custom-web-ui repair policy scheduler tick.

Usage:
  python3 scripts/run_repair_policy_tick.py

Environment variables:
  CUSTOM_UI_BASE_URL  default: http://127.0.0.1:8000
  CUSTOM_UI_USERNAME  default: admin
  CUSTOM_UI_PIN       default: 1234
  CUSTOM_UI_FORCE     default: false (true/false)
"""

from __future__ import annotations
import json
import os
import urllib.request

BASE = os.getenv("CUSTOM_UI_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
USERNAME = os.getenv("CUSTOM_UI_USERNAME", "admin")
PIN = os.getenv("CUSTOM_UI_PIN", "1234")
FORCE = os.getenv("CUSTOM_UI_FORCE", "false").lower() in {"1", "true", "yes", "on"}


def req(path: str, method: str = "GET", data: dict | None = None, token: str | None = None) -> dict:
    body = None
    headers = {}
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["x-session-token"] = token
    r = urllib.request.Request(BASE + path, data=body, method=method, headers=headers)
    with urllib.request.urlopen(r, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> None:
    login = req("/api/auth/login", method="POST", data={"username": USERNAME, "pin": PIN})
    token = login["token"]
    out = req(f"/api/llm-wikis/lint/repair-report/policy/tick?force={'true' if FORCE else 'false'}", method="POST", token=token)
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
