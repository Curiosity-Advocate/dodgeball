// DodgeballPlus Live — injects a small panel on a YouTube watch page that lists
// in-progress games by name and, when one is picked, shows its live score over the
// match WebSocket. The content script does everything (network + UI); host
// permissions for the API let it reach the server despite YouTube's page CSP.
(() => {
  const API = "https://dodgeball-rqt0.onrender.com";
  const WS = "wss://dodgeball-rqt0.onrender.com";
  const PANEL_ID = "dbp-panel";

  if (document.getElementById(PANEL_ID)) return; // already injected on this page

  let socket = null;

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

  // ---- view: live ticker for one game ----
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
      <div class="dbp-status" data-status>Round ${game.score_home + game.score_away} · live</div>`;

    body.querySelector(".dbp-back").onclick = showGames;
    const home = body.querySelector("[data-home]");
    const away = body.querySelector("[data-away]");
    const status = body.querySelector("[data-status]");

    connect(game.id, (state) => {
      home.textContent = state.score_home;
      away.textContent = state.score_away;
      status.textContent = statusLabel(state, game);
    });
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
