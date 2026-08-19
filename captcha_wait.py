#!/usr/bin/env python3
"""Wait for a CAPTCHA marker without attaching CDP to the page target."""

from __future__ import annotations

import argparse
import json
import time
import urllib.request

SOLVED_PREFIX = "__HERMES_CAPTCHA_SOLVED__"


def targets(cdp_url: str) -> list[dict]:
    with urllib.request.urlopen(f"{cdp_url.rstrip('/')}/json/list", timeout=3) as response:
        value = json.loads(response.read())
    return value if isinstance(value, list) else []


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("target_id")
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--cdp-url", default="http://127.0.0.1:9222")
    args = parser.parse_args()

    started = time.monotonic()
    deadline = started + max(1, min(args.timeout, 1800))
    while time.monotonic() < deadline:
        try:
            page = next((item for item in targets(args.cdp_url) if item.get("id") == args.target_id), None)
        except Exception as exc:
            print(json.dumps({"solved": False, "status": "cdp_error", "error": str(exc)}))
            return 2
        if page is None:
            print(json.dumps({"solved": False, "status": "target_closed"}))
            return 1
        if str(page.get("title") or "").startswith(SOLVED_PREFIX):
            print(json.dumps({
                "solved": True,
                "status": "solved",
                "elapsed_s": round(time.monotonic() - started, 1),
                "target_id": args.target_id,
            }))
            return 0
        time.sleep(1)

    print(json.dumps({
        "solved": False,
        "status": "timeout",
        "elapsed_s": round(time.monotonic() - started, 1),
        "target_id": args.target_id,
    }))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
