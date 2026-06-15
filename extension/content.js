// DodgeballPlus Live — injects a panel on a YouTube watch page that lists in-progress
// games by name and, when one is picked, shows its live score over the match
// WebSocket. Signed-in scorekeepers also get scoring buttons. The content script does
// everything (network + UI); host permissions for the API let it reach the server
// despite YouTube's page CSP.
(() => {
  const API = "https://dodgeball-rqt0.onrender.com";
  const WS = "wss://dodgeball-rqt0.onrender.com";
  const PANEL_ID = "dbp-panel";
  const SESSION_MAX_MS = 5 * 60 * 60 * 1000; // absolute cap: re-auth after 5 hours

  if (document.getElementById(PANEL_ID)) return; // already injected on this page

  let socket = null;

  // ---- auth: access + refresh in chrome.storage.local, 5h absolute cap ----
  const auth = {
    async current() {
      const s = await chrome.storage.local.get(["access_token", "expires_at", "email"]);
      if (!s.access_token) return null;
      if (s.expires_at && Date.now() > s.expires_at) {
        await this.signOut(); // past the absolute cap: revoke + clear
        return null;
      }
      return s;
    },
    async signIn(email, password) {
      const tokens = await postJson("/auth/login", { email, password });
      await chrome.storage.local.set({
        access_token: tokens.access_token,
        refresh_token: tokens.refresh_token,
        expires_at: Date.now() + SESSION_MAX_MS, // absolute — does not slide on refresh
        email,
      });
    },
    async refresh() {
      const s = await chrome.storage.local.get(["refresh_token", "expires_at"]);
      if (!s.refresh_token || (s.expires_at && Date.now() > s.expires_at)) {
        await this.signOut();
        return null;
      }
      try {
        const tokens = await postJson("/auth/refresh", { refresh_token: s.refresh_token });
        await chrome.storage.local.set({
          access_token: tokens.access_token,
          refresh_token: tokens.refresh_token, // rotated; keep the same absolute expiry
        });
        return tokens.access_token;
      } catch {
        await this.signOut();
        return null;
      }
    },
    async signOut() {
      const s = await chrome.storage.local.get("refresh_token");
      if (s.refresh_token) {
        try {
          await postJson("/auth/logout", { refresh_token: s.refresh_token }); // server revoke
        } catch {
          /* best effort */
        }
      }
      await chrome.storage.local.remove(["access_token", "refresh_token", "expires_at", "email"]);
    },
  };

  async function postJson(path, body, token) {
    const headers = { "Content-Type": "application/json" };
    if (token) headers.Authorization = `Bearer ${token}`;
    const res = await fetch(`${API}${path}`, {
      method: "POST",
      headers,
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(`${path} -> ${res.status}`);
    return res.json();
  }

  // Publish an event, refreshing the access token once on a 401.
  async function score(matchId, type) {
    const send = (token) =>
      fetch(`${API}/matches/${matchId}/events`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ type, payload: {}, idempotency_key: crypto.randomUUID() }),
      });

    let token = (await chrome.storage.local.get("access_token")).access_token;
    if (!token) return "signed_out";
    let res = await send(token);
    if (res.status === 401) {
      token = await auth.refresh();
      if (!token) return "signed_out";
      res = await send(token);
    }
    if (res.status === 403) return "forbidden";
    return res.ok ? "ok" : "error";
  }

  // ---- panel shell ----
  const panel = document.createElement("div");
  panel.id = PANEL_ID;
  panel.innerHTML = `
    <div class="dbp-header">
      <span class="dbp-title">DodgeballPlus · Live</span>
      <button class="dbp-close" title="Hide">×</button>
    </div>
    <div class="dbp-body"></div>`;
  document.body.appendChild(panel);

  const body = panel.querySelector(".dbp-body");
  panel.querySelector(".dbp-close").onclick = () => {
    closeSocket();
    panel.remove();
  };

  function esc(value) {
    const d = document.createElement("div");
    d.textContent = value == null ? "" : String(value);
    return d.innerHTML;
  }

  function statusLabel(state, game) {
    if (state.status === "final") {
      if (state.score_home > state.score_away) return `Final · ${game.home_team_name} win`;
      if (state.score_away > state.score_home) return `Final · ${game.away_team_name} win`;
      return "Final · draw";
    }
    return `Round ${state.current_round} · live`;
  }

  // ---- view: list of in-progress games ----
  async function showGames() {
    closeSocket();
    body.innerHTML = `<div class="dbp-muted">Loading live games…</div>`;
    let games;
    try {
      const res = await fetch(`${API}/matches?status=in_progress`);
      games = (await res.json()).matches || [];
    } catch {
      return renderMessage("Couldn't reach the server.", "Retry");
    }
    if (games.length === 0) {
      return renderMessage("No live games right now.", "Refresh");
    }
    body.innerHTML = `<div class="dbp-section">Now playing</div>`;
    for (const game of games) {
      const item = document.createElement("button");
      item.className = "dbp-game";
      item.innerHTML =
        `<span class="dbp-teams">${esc(game.home_team_name)} ` +
        `<b>${game.score_home}–${game.score_away}</b> ${esc(game.away_team_name)}</span>` +
        `<span class="dbp-comp">${esc(game.competition_name)}</span>`;
      item.onclick = () => showTicker(game);
      body.appendChild(item);
    }
    appendButton("Refresh", showGames);
  }

  function renderMessage(text, buttonLabel) {
    body.innerHTML = `<div class="dbp-muted">${esc(text)}</div>`;
    appendButton(buttonLabel, showGames);
  }

  function appendButton(label, onClick) {
    const button = document.createElement("button");
    button.className = "dbp-btn";
    button.textContent = label;
    button.onclick = onClick;
    body.appendChild(button);
  }

  // ---- view: live ticker for one game (+ scorekeeper controls) ----
  function showTicker(game) {
    body.innerHTML = `
      <button class="dbp-back">← games</button>
      <div class="dbp-comp">${esc(game.competition_name)}</div>
      <div class="dbp-score">
        <div class="dbp-team">
          <div class="dbp-name">${esc(game.home_team_name)}</div>
          <div class="dbp-points" data-home>${game.score_home}</div>
        </div>
        <div class="dbp-sep">–</div>
        <div class="dbp-team">
          <div class="dbp-name">${esc(game.away_team_name)}</div>
          <div class="dbp-points" data-away>${game.score_away}</div>
        </div>
      </div>
      <div class="dbp-status" data-status>Round ${game.score_home + game.score_away} · live</div>
      <div class="dbp-sk" data-sk></div>`;

    body.querySelector(".dbp-back").onclick = showGames;
    const home = body.querySelector("[data-home]");
    const away = body.querySelector("[data-away]");
    const status = body.querySelector("[data-status]");

    connect(game.id, (state) => {
      home.textContent = state.score_home;
      away.textContent = state.score_away;
      status.textContent = statusLabel(state, game);
    });

    renderScorekeeper(game);
  }

  // ---- scorekeeper controls (only the panel below the ticker re-renders) ----
  async function renderScorekeeper(game) {
    const sk = body.querySelector("[data-sk]");
    if (!sk) return; // ticker view was replaced
    const session = await auth.current();
    if (!session) {
      sk.innerHTML = `<button class="dbp-link" data-signin>Sign in to score</button>`;
      sk.querySelector("[data-signin]").onclick = () => renderLogin(game);
      return;
    }
    sk.innerHTML = `
      <div class="dbp-section">Scorekeeper</div>
      <div class="dbp-actions">
        <button data-ev="match_started">Start</button>
        <button data-ev="round_won_home">Home +1</button>
        <button data-ev="round_won_away">Away +1</button>
        <button data-ev="match_finalised">Finalise</button>
      </div>
      <div class="dbp-err" data-err></div>
      <div class="dbp-who">${esc(session.email)} · <button class="dbp-link" data-out>sign out</button></div>`;

    const err = sk.querySelector("[data-err]");
    sk.querySelector("[data-out]").onclick = async () => {
      await auth.signOut();
      renderScorekeeper(game);
    };
    for (const btn of sk.querySelectorAll("[data-ev]")) {
      btn.onclick = async () => {
        err.textContent = "";
        const result = await score(game.id, btn.dataset.ev);
        if (result === "forbidden") err.textContent = "You're not the scorekeeper for this match.";
        else if (result === "signed_out") renderLogin(game);
        else if (result === "error") err.textContent = "Couldn't publish that event.";
        // on success the WebSocket pushes the new state into the ticker
      };
    }
  }

  function renderLogin(game) {
    const sk = body.querySelector("[data-sk]");
    if (!sk) return;
    sk.innerHTML = `
      <div class="dbp-section">Sign in to score</div>
      <form class="dbp-form">
        <input type="email" placeholder="email" autocomplete="username" data-email>
        <input type="password" placeholder="password" autocomplete="current-password" data-pw>
        <button type="submit">Sign in</button>
      </form>
      <div class="dbp-err" data-err></div>
      <button class="dbp-link" data-cancel>cancel</button>`;

    const err = sk.querySelector("[data-err]");
    sk.querySelector("[data-cancel]").onclick = () => renderScorekeeper(game);
    sk.querySelector(".dbp-form").onsubmit = async (event) => {
      event.preventDefault();
      err.textContent = "";
      try {
        await auth.signIn(
          sk.querySelector("[data-email]").value.trim(),
          sk.querySelector("[data-pw]").value
        );
        renderScorekeeper(game);
      } catch {
        err.textContent = "Invalid email or password.";
      }
    };
  }

  // ---- websocket: replay from the start, then live ----
  function connect(matchId, onState) {
    closeSocket();
    socket = new WebSocket(`${WS}/matches/${matchId}`);
    socket.onopen = () => socket.send(JSON.stringify({ last_version: 0 }));
    socket.onmessage = (event) => onState(JSON.parse(event.data).state);
  }

  function closeSocket() {
    if (socket) {
      socket.onclose = null;
      socket.close();
      socket = null;
    }
  }

  showGames();
})();
