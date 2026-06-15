# DodgeballPlus Live — Chrome extension

A small overlay that shows live dodgeball scores beside a YouTube video. It lists the
matches currently in progress and, when you pick one, streams its score over the match
WebSocket — no login needed to watch.

## Load it (unpacked)

1. Open `chrome://extensions`.
2. Turn on **Developer mode** (top-right).
3. **Load unpacked** → select this `extension/` folder.
4. Open any YouTube watch page (`https://www.youtube.com/watch?…`). A
   **DodgeballPlus · Live** panel appears top-right.

## Try it

If no real game is on, start one against the live demo (from the repo root):

```sh
BASE=https://dodgeball-rqt0.onrender.com python3 examples/simulate.py
```

The panel's "Now playing" list then shows the demo game; click it to watch the score
tick up live. Stop the simulator with Ctrl-C (it finalises the match).

## Notes

- Targets Chromium (Chrome, Edge, Brave). Manifest V3, vanilla JS — no build step.
- Talks to `https://dodgeball-rqt0.onrender.com`; change `API`/`WS` at the top of
  `content.js` to point at your own instance.
- Watching is public. Publishing scores from a scorekeeper panel is a later iteration.
