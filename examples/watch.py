"""Watch a match live over WebSocket: replay the events so far, then print each
new one as it arrives, with the running score. Pair it with simulate.py.

    pip install websockets
    WS=wss://dodgeball-rqt0.onrender.com python3 examples/watch.py
    # local instead:  WS=ws://localhost:8000 python3 examples/watch.py

Disconnect and restart mid-match and it replays whatever it missed — no update is
ever lost.
"""

import asyncio
import json
import os

import websockets

WS = os.environ.get("WS", "wss://dodgeball-rqt0.onrender.com")
MATCH_ID = os.environ.get("MATCH_ID", "1")


async def main() -> None:
    async with websockets.connect(f"{WS}/matches/{MATCH_ID}") as sock:
        await sock.send(json.dumps({"last_version": 0}))  # replay from the start
        print(f"watching /matches/{MATCH_ID} ... (Ctrl-C to stop)")
        async for message in sock:
            event = json.loads(message)
            state = event["state"]
            print(
                f"v{event['version']:>3}  {event['type']:<16} "
                f"{state['score_home']}-{state['score_away']}  ({state['status']})",
                flush=True,
            )


if __name__ == "__main__":
    asyncio.run(main())
