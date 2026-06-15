# DodgeballPlus

Live dodgeball scoring on an event-sourced log: an authorised scorekeeper publishes
scoring events during a match, any number of spectators receive updates instantly
over WebSocket with a reliable reconnect, and standings recompute automatically.

**Live demo:** <https://dodgeball-rqt0.onrender.com/docs> — interactive API (Swagger).
*(Free tier; the first request after idle cold-starts in ~30–50s.)*

## Prerequisites

To run it yourself:

- **Python 3.12**
- **[uv](https://docs.astral.sh/uv/)** (package manager)
- **PostgreSQL 13+** — local, or a managed instance (Neon, Render, …). The schema
  uses `citext` and `gen_random_uuid()`, both standard on 13+.

## Run it locally

```sh
git clone https://github.com/Curiosity-Advocate/dodgeball
cd dodgeball
uv sync

# Point at your Postgres. Any scheme works — the app normalises postgres:// and
# ?sslmode=require to the async form it needs.
export DATABASE_URL="postgresql+asyncpg://USER:PASS@localhost:5432/dodgeball"

uv run alembic upgrade head      # create the schema
uv run python -m app.seed        # demo competition / match / scorekeeper
uv run uvicorn app.api.main:app --reload
```

Open <http://localhost:8000/docs>.

### Or with Docker

```sh
docker build -t dodgeball .
docker run -p 8000:8000 -e DATABASE_URL="postgres://USER:PASS@HOST/db" dodgeball
```

The image's entrypoint migrates, seeds, then serves — so a managed URL (e.g. Neon's
`postgres://…?sslmode=require`) works as-is.

## See it live: publish events, watch them arrive

The headline feature is real-time fan-out — when a scorekeeper publishes an event,
every spectator sees it instantly. Two small scripts demonstrate it: one **publishes**
a live match, the other **subscribes** and prints each event as it lands. Run them
side by side (against the live demo, or your local server).

Point them at a target:

```sh
export BASE=https://dodgeball-rqt0.onrender.com
export WS=wss://dodgeball-rqt0.onrender.com
# local instead:  export BASE=http://localhost:8000  WS=ws://localhost:8000
```

**Terminal A — subscribe and watch:**

```sh
pip install websockets
python3 examples/watch.py
# watching /matches/1 ...   (replays the match so far, then waits for live events)
```

**Terminal B — publish a live match:**

```sh
python3 examples/simulate.py
# logs in as the seeded scorekeeper and streams events every ~2s (Ctrl-C finalises)
```

As Terminal B publishes, Terminal A prints each event the instant it arrives, with the
running score:

```
v  1  match_started    0-0  (in_progress)
v  2  round_won_home   1-0  (in_progress)
v  3  round_won_away   1-1  (in_progress)
v  4  round_won_home   2-1  (in_progress)
```

Kill `watch.py` mid-match and restart it — it replays everything it missed before
resuming live. **No update is ever lost across a disconnect.** That guarantee comes
from the event log: the live socket is best-effort, and a reconnecting client catches
up by replaying from the durable log.

> Why a *seeded* scorekeeper? Publishing to a match is restricted to that match's
> assigned scorekeeper or an admin (a deliberate control). The seed creates
> `scorekeeper@demo.local`, assigned to match 1, and `simulate.py` logs in as it.

> On macOS, if a script fails with `CERTIFICATE_VERIFY_FAILED`, your Python is
> missing CA certificates — run the bundled `Install Certificates.command`, or
> prefix the command with `SSL_CERT_FILE=/etc/ssl/cert.pem`.

## The auth flow (optional)

The API has full account auth — register, login, rotating refresh tokens. To try it:

```sh
# register a new account
curl -s $BASE/auth/register -H 'Content-Type: application/json' \
  -d '{"email":"you@example.com","password":"password123","display_name":"You"}'

# log in -> access token, then check who you are
TOKEN=$(curl -s $BASE/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"you@example.com","password":"password123"}' \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])')
curl -s $BASE/auth/me -H "Authorization: Bearer $TOKEN"
```

Reading is public (`$BASE/matches`, `$BASE/matches/1/snapshot`,
`$BASE/competitions/1/standings`); only publishing requires a token.

## Documentation

The full design lives in [`docs/`](docs/) — start with
[`docs/overview.md`](docs/overview.md). Running and deployment details are in
[`docs/operations/`](docs/operations/).
