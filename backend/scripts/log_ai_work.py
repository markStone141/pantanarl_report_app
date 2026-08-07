#!/usr/bin/env python3
"""Append AI work events to repository-local log files."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


REPO_ROOT = Path(__file__).resolve().parents[2]
LOG_DIR = REPO_ROOT / "logs"
EXECUTION_LOG = LOG_DIR / "execution.json"
ERROR_LOG = LOG_DIR / "errors.json"
SENSITIVE_LOG = LOG_DIR / "sensitive.json"
SUMMARY_LOG = LOG_DIR / "latest-summary.md"
TOKYO = ZoneInfo("Asia/Tokyo")
RETENTION_DAYS = {
    "execution": 30,
    "error": 90,
    "summary": 365,
    "sensitive": 7,
}
AGENT_ROLES = [
    "agent",
    "planner",
    "implementer",
    "observer",
    "validator",
    "test_agent",
    "ui_designer",
    "reviewer",
    "repairer",
    "reporter",
]
SENSITIVE_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"password\s*[:=]",
        r"passwd\s*[:=]",
        r"api[_ -]?key\s*[:=]",
        r"access[_ -]?token\s*[:=]",
        r"refresh[_ -]?token\s*[:=]",
        r"authorization\s*[:=]\s*bearer\s+",
        r"cookie\s*[:=]",
        r"set-cookie\s*[:=]",
        r"secret[_ -]?key\s*[:=]",
        r"client[_ -]?secret\s*[:=]",
        r"db[_ -]?password\s*[:=]",
        r"env(?:ironment)?\s*(?:dump|variables|全内容)",
        r"\b(?:\d[ -]*?){13,19}\b",
        r"パスワード",
        r"APIキー",
        r"アクセストークン",
        r"リフレッシュトークン",
        r"Cookie",
        r"クレジットカード",
        r"環境変数",
    ]
]


def _load_events(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, list):
        raise ValueError(f"{path} must contain a JSON array")
    return data


def _write_events(path: Path, events: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(events, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def _parse_timestamp(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _expires_at(*, timestamp: datetime, retention_key: str) -> str:
    return (timestamp + timedelta(days=RETENTION_DAYS[retention_key])).isoformat(timespec="seconds")


def _prune_events(events: list[dict], *, now: datetime, retention_key: str) -> list[dict]:
    cutoff = now - timedelta(days=RETENTION_DAYS[retention_key])
    kept = []
    for event in events:
        expires_at = _parse_timestamp(str(event.get("expires_at") or ""))
        if expires_at is not None:
            if expires_at >= now:
                kept.append(event)
            continue
        timestamp = _parse_timestamp(str(event.get("timestamp") or ""))
        if timestamp is None or timestamp >= cutoff:
            kept.append(event)
    return kept


def _sensitive_matches(values: list[str]) -> list[str]:
    joined = "\n".join(values)
    matches = []
    for pattern in SENSITIVE_PATTERNS:
        if pattern.search(joined):
            matches.append(pattern.pattern)
    return matches


def _write_summary(event: dict) -> None:
    timestamp = _parse_timestamp(str(event["timestamp"]))
    summary_expires_at = (
        _expires_at(timestamp=timestamp, retention_key="summary")
        if timestamp is not None
        else event["expires_at"]
    )
    lines = [
        "# Latest AI Work Summary",
        "",
        f"- Timestamp: `{event['timestamp']}`",
        f"- Run ID: `{event['run_id']}`",
        f"- Loop: `{event['loop']}`",
        f"- Role: `{event.get('role', 'agent')}`",
        f"- Event: `{event['event']}`",
        f"- Status: `{event['status']}`",
        f"- Event Retention: `{event['retention_days']} days`",
        f"- Event Expires At: `{event['expires_at']}`",
        f"- Summary Retention: `{RETENTION_DAYS['summary']} days`",
        f"- Summary Expires At: `{summary_expires_at}`",
        f"- Sensitivity: `{event['sensitivity']}`",
        "",
        "## Action",
        "",
        event["action"],
        "",
        "## Reason",
        "",
        event["reason"],
        "",
        "## Next Action",
        "",
        event["next_action"],
    ]
    SUMMARY_LOG.write_text("\n".join(lines) + "\n", encoding="utf-8")


def append_event(
    *,
    run_id: str,
    loop: int,
    event: str,
    status: str,
    action: str,
    reason: str,
    next_action: str,
    role: str = "agent",
    sensitivity: str = "normal",
    allow_sensitive: bool = False,
) -> dict:
    sensitive_matches = _sensitive_matches([run_id, role, event, status, action, reason, next_action])
    if sensitive_matches and not allow_sensitive:
        raise ValueError(
            "ログ内容に機密情報を含む可能性があります。内容を要約/マスクするか、"
            "--sensitivity sensitive --allow-sensitive を明示してください。"
        )
    if sensitive_matches and sensitivity != "sensitive":
        raise ValueError("機密情報を含む可能性があるログは --sensitivity sensitive が必要です。")

    timestamp_dt = datetime.now(TOKYO)
    timestamp = timestamp_dt.isoformat(timespec="seconds")
    retention_key = "sensitive" if sensitivity == "sensitive" else ("error" if status in {"fail", "error", "blocked"} else "execution")
    payload = {
        "timestamp": timestamp,
        "expires_at": _expires_at(timestamp=timestamp_dt, retention_key=retention_key),
        "retention_days": RETENTION_DAYS[retention_key],
        "run_id": run_id,
        "loop": loop,
        "role": role,
        "event": event,
        "status": status,
        "sensitivity": sensitivity,
        "sensitive_match_count": len(sensitive_matches),
        "action": action,
        "reason": reason,
        "next_action": next_action,
    }

    target = SENSITIVE_LOG if sensitivity == "sensitive" else (ERROR_LOG if status in {"fail", "error", "blocked"} else EXECUTION_LOG)
    events = _load_events(target)
    events = _prune_events(events, now=timestamp_dt, retention_key=retention_key)
    events.append(payload)
    _write_events(target, events)
    _write_summary(payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Append an AI work log event.")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--loop", type=int, default=1)
    parser.add_argument("--role", choices=AGENT_ROLES, default="agent")
    parser.add_argument("--event", required=True)
    parser.add_argument("--status", required=True, choices=["success", "fail", "error", "blocked", "info"])
    parser.add_argument("--action", required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--next-action", required=True)
    parser.add_argument("--sensitivity", choices=["normal", "sensitive"], default="normal")
    parser.add_argument(
        "--allow-sensitive",
        action="store_true",
        help="Confirm that this event may include sensitive information. Prefer masking instead.",
    )
    args = parser.parse_args()

    try:
        payload = append_event(
            run_id=args.run_id,
            loop=args.loop,
            event=args.event,
            status=args.status,
            action=args.action,
            reason=args.reason,
            next_action=args.next_action,
            role=args.role,
            sensitivity=args.sensitivity,
            allow_sensitive=args.allow_sensitive,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from exc
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
