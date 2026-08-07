#!/usr/bin/env python3
"""Append AI work events to repository-local log files."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


REPO_ROOT = Path(__file__).resolve().parents[2]
LOG_DIR = REPO_ROOT / "logs"
EXECUTION_LOG = LOG_DIR / "execution.json"
ERROR_LOG = LOG_DIR / "errors.json"
SUMMARY_LOG = LOG_DIR / "latest-summary.md"
TOKYO = ZoneInfo("Asia/Tokyo")


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


def _write_summary(event: dict) -> None:
    lines = [
        "# Latest AI Work Summary",
        "",
        f"- Timestamp: `{event['timestamp']}`",
        f"- Run ID: `{event['run_id']}`",
        f"- Loop: `{event['loop']}`",
        f"- Event: `{event['event']}`",
        f"- Status: `{event['status']}`",
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


def append_event(*, run_id: str, loop: int, event: str, status: str, action: str, reason: str, next_action: str) -> dict:
    timestamp = datetime.now(TOKYO).isoformat(timespec="seconds")
    payload = {
        "timestamp": timestamp,
        "run_id": run_id,
        "loop": loop,
        "event": event,
        "status": status,
        "action": action,
        "reason": reason,
        "next_action": next_action,
    }

    target = ERROR_LOG if status in {"fail", "error", "blocked"} else EXECUTION_LOG
    events = _load_events(target)
    events.append(payload)
    _write_events(target, events)
    _write_summary(payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Append an AI work log event.")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--loop", type=int, default=1)
    parser.add_argument("--event", required=True)
    parser.add_argument("--status", required=True, choices=["success", "fail", "error", "blocked", "info"])
    parser.add_argument("--action", required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--next-action", required=True)
    args = parser.parse_args()

    payload = append_event(
        run_id=args.run_id,
        loop=args.loop,
        event=args.event,
        status=args.status,
        action=args.action,
        reason=args.reason,
        next_action=args.next_action,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
