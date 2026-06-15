"""Simulate a live match: log in as the seeded scorekeeper and stream scoring
events to match 1, like a real game unfolding. Pair it with watch.py to see the
events arrive live on the subscriber side.

    BASE=https://dodgeball-rqt0.onrender.com python3 examples/simulate.py
    # local instead:  BASE=http://localhost:8000 python3 examples/simulate.py

Stops on Ctrl-C, finalising the match. Uses only the standard library.
"""

import json
import os
import random
import time
import urllib.request
import uuid

BASE = os.environ.get("BASE", "https://dodgeball-rqt0.onrender.com")
MATCH_ID = os.environ.get("MATCH_ID", "1")


def _post(path: str, body: dict, token: str | None = None) -> dict:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        f"{BASE}{path}", data=json.dumps(body).encode(), headers=headers, method="POST"
    )
    with urllib.request.urlopen(request) as response:  # noqa: S310 — fixed, trusted BASE
        return json.load(response)


def main() -> None:
    token = _post(
        "/auth/login",
        {"email": "scorekeeper@demo.local", "password": "demo-password"},
    )["access_token"]

    def publish(event_type: str) -> None:
        state = _post(
            f"/matches/{MATCH_ID}/events",
            {"type": event_type, "payload": {}, "idempotency_key": str(uuid.uuid4())},
            token,
        )["state"]
        print(
            f"published {event_type:<16} -> {state['score_home']}-{state['score_away']}",
            flush=True,
        )

    print(f"Streaming a live match on /matches/{MATCH_ID} ... (Ctrl-C to finalise)")
    publish("match_started")
    try:
        while True:
            time.sleep(2)
            publish(random.choice(["round_won_home", "round_won_away"]))  # noqa: S311 — demo only
    except KeyboardInterrupt:
        publish("match_finalised")
        print("\nmatch finalised.")


if __name__ == "__main__":
    main()
