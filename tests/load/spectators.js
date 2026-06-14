// Load & measurement harness (NFR-3, NFR-14). No pass/fail thresholds are set —
// this measures, it doesn't gate (testing-strategy.md). Two scenarios run together:
//   spectators — N held WebSocket connections (the NFR-1 connection ceiling)
//   scorer     — one writer posting round events at a human pace, driving live updates
//
// Target is configurable so the same script runs against a local app or the
// deployment:  BASE_URL, WS_URL, MATCH_ID, TOKEN, VUS, DURATION, HOLD_MS.
import ws from 'k6/ws';
import http from 'k6/http';
import { check } from 'k6';
import { Trend, Counter } from 'k6/metrics';

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000';
const WS_URL = __ENV.WS_URL || 'ws://localhost:8000';
const MATCH_ID = __ENV.MATCH_ID || '1';
const TOKEN = __ENV.TOKEN || '';
const VUS = parseInt(__ENV.VUS || '200', 10);
const DURATION = __ENV.DURATION || '30s';
const HOLD_MS = parseInt(__ENV.HOLD_MS || '20000', 10);

// Time from opening a socket to the first server message (replay/snapshot latency).
const firstMessageLatency = new Trend('ws_first_message_latency', true);
const messagesReceived = new Counter('ws_messages_received');

export const options = {
  scenarios: {
    spectators: { executor: 'constant-vus', exec: 'spectator', vus: VUS, duration: DURATION },
    scorer: {
      executor: 'constant-arrival-rate',
      exec: 'scorer',
      rate: 1,
      timeUnit: '1s',
      duration: DURATION,
      preAllocatedVUs: 2,
    },
  },
};

function uuidv4() {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16);
  });
}

export function spectator() {
  const start = Date.now();
  let first = true;
  ws.connect(`${WS_URL}/matches/${MATCH_ID}`, {}, (socket) => {
    socket.on('open', () => socket.send(JSON.stringify({ last_version: 0 })));
    socket.on('message', () => {
      messagesReceived.add(1);
      if (first) {
        firstMessageLatency.add(Date.now() - start);
        first = false;
      }
    });
    socket.setTimeout(() => socket.close(), HOLD_MS);
  });
}

export function scorer() {
  const types = ['round_won_home', 'round_won_away'];
  const body = JSON.stringify({
    type: types[Math.floor(Math.random() * types.length)],
    idempotency_key: uuidv4(),
    payload: {},
  });
  const res = http.post(`${BASE_URL}/matches/${MATCH_ID}/events`, body, {
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${TOKEN}` },
  });
  check(res, { 'event accepted': (r) => r.status === 201 || r.status === 200 });
}
