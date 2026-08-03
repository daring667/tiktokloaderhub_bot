// Snake, plus the chaos that lands on it after every apple.

import {
  APPLES_TO_CLEAR_DAY, BASE_POINTS_PER_APPLE, CHAOS_BONUS_PER_MODIFIER,
  MAX_PERMANENT_MODIFIERS, PERMANENT, TIMED, RARITY_LABEL,
  dayKey, eventCode, mulberry32, rollEvent, seedForDay,
} from './chaos.js';

const GRID = 18;
const BASE_TICK_MS = 150;
const SPEED_STEP = 1.2;

// The snake holds still for a moment after each event. Some modifiers —
// mirror, reverse — change where everything appears to be, and without a
// beat to re-read the board a player heading for an apple near the edge
// just dies, with no idea why. The pause is also when the banner is read.
const EVENT_PAUSE_MS = 850;

const tg = window.Telegram?.WebApp;

const canvas = document.getElementById('board');
const ctx = canvas.getContext('2d');
const els = {
  apples: document.getElementById('apples'),
  score: document.getElementById('score'),
  mods: document.getElementById('mods'),
  toast: document.getElementById('toast'),
  over: document.getElementById('over'),
  overTitle: document.getElementById('over-title'),
  overStats: document.getElementById('over-stats'),
  send: document.getElementById('send'),
  again: document.getElementById('again'),
  day: document.getElementById('day'),
  start: document.getElementById('start'),
  play: document.getElementById('play'),
};

let state = null;
let today = dayKey();
let daySeed = 0;

function freshState() {
  return {
    snake: [{ x: 9, y: 9 }, { x: 8, y: 9 }, { x: 7, y: 9 }],
    dir: { x: 1, y: 0 },
    queuedDir: null,
    apples: [],
    walls: [],
    permanent: [],          // event ids, oldest first
    timed: [],              // { id, until, multiplier }
    golden: false,
    pausedUntil: 0,
    score: 0,
    eaten: 0,
    chain: [],
    startedAt: performance.now(),
    over: false,
    // Two independent streams. The event stream is consumed exactly two
    // draws per apple, because the bot replays it to validate the run; if
    // apple and wall placement drew from it too, the chains would diverge.
    eventRand: mulberry32(daySeed),
    worldRand: mulberry32((daySeed ^ 0x9e3779b9) >>> 0),
  };
}

// --- derived effects -------------------------------------------------

const count = (id) => state.permanent.filter((m) => m === id).length;
const has = (id) => state.permanent.includes(id);
const timedActive = (id) => state.timed.some((t) => t.id === id);

const speedFactor = () => SPEED_STEP ** count('speed');
const wraps = () => count('portal') % 2 === 1;
const mirrored = () => count('mirror') % 2 === 1;

function tickInterval() {
  return BASE_TICK_MS / speedFactor();
}

function chaosMultiplier() {
  return 1 + CHAOS_BONUS_PER_MODIFIER * state.permanent.length;
}

// --- world helpers ---------------------------------------------------

function freeCell() {
  for (let attempt = 0; attempt < 200; attempt += 1) {
    const cell = {
      x: Math.floor(state.worldRand() * GRID),
      y: Math.floor(state.worldRand() * GRID),
    };
    const taken = state.snake.some((s) => s.x === cell.x && s.y === cell.y)
      || state.walls.some((w) => w.x === cell.x && w.y === cell.y)
      || state.apples.some((a) => a.x === cell.x && a.y === cell.y);
    if (!taken) return cell;
  }
  return { x: 0, y: 0 };
}

function syncApples() {
  const wanted = has('twins') ? 2 : 1;
  while (state.apples.length < wanted) state.apples.push(freeCell());
  while (state.apples.length > wanted) state.apples.pop();
}

function syncWalls() {
  const wanted = count('walls') * 3;
  while (state.walls.length < wanted) state.walls.push(freeCell());
  while (state.walls.length > wanted) state.walls.pop();
}

// --- events ----------------------------------------------------------

function addPermanent(id) {
  state.permanent.push(id);
  // Stacking is the point, but past four the run stops being playable, so
  // the oldest falls off.
  if (state.permanent.length > MAX_PERMANENT_MODIFIERS) state.permanent.shift();
  syncWalls();
  syncApples();
}

function reverseSnake() {
  state.snake.reverse();
  const [head, next] = state.snake;
  if (next) state.dir = { x: Math.sign(head.x - next.x), y: Math.sign(head.y - next.y) };
}

function applyEvent(event) {
  if (event.kind === PERMANENT) {
    addPermanent(event.id);
  } else if (event.kind === TIMED) {
    state.timed.push({
      id: event.id,
      until: performance.now() + event.duration * 1000,
      multiplier: event.multiplier || 1,
    });
    if (event.id === 'reverse') reverseSnake();
  } else if (event.id === 'growth') {
    const tail = state.snake[state.snake.length - 1];
    state.snake.push({ ...tail }, { ...tail });
  } else if (event.id === 'golden') {
    state.golden = true;
  }
  showToast(event);
  state.pausedUntil = performance.now() + EVENT_PAUSE_MS;
  // A turn queued a moment before the board flipped was aimed at the old
  // layout; carrying it over would steer somewhere the player never meant.
  state.queuedDir = null;
}

function expireTimed(now) {
  state.timed = state.timed.filter((t) => {
    if (t.until > now) return true;
    if (t.id === 'reverse') reverseSnake();  // and back again
    return false;
  });
}

function showToast(event) {
  els.toast.textContent = `${RARITY_LABEL[event.rarity]} ${event.title} — ${event.text}`;
  els.toast.className = `toast show ${event.rarity}`;
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => { els.toast.className = 'toast'; }, 1800);
}

// --- the loop --------------------------------------------------------

function step() {
  if (state.queuedDir) {
    state.dir = state.queuedDir;
    state.queuedDir = null;
  }

  const head = state.snake[0];
  let nx = head.x + state.dir.x;
  let ny = head.y + state.dir.y;

  if (wraps()) {
    nx = (nx + GRID) % GRID;
    ny = (ny + GRID) % GRID;
  } else if (nx < 0 || ny < 0 || nx >= GRID || ny >= GRID) {
    return gameOver();
  }

  if (state.walls.some((w) => w.x === nx && w.y === ny)) return gameOver();
  if (state.snake.some((s, i) => i < state.snake.length - 1 && s.x === nx && s.y === ny)) {
    return gameOver();
  }

  state.snake.unshift({ x: nx, y: ny });

  const eatenIndex = state.apples.findIndex((a) => a.x === nx && a.y === ny);
  if (eatenIndex === -1) {
    state.snake.pop();
    return;
  }

  state.apples.splice(eatenIndex, 1);
  state.eaten += 1;

  const timedMultiplier = state.timed.reduce((m, t) => m * (t.multiplier || 1), 1);
  const goldenMultiplier = state.golden ? 5 : 1;
  state.golden = false;
  state.score += BASE_POINTS_PER_APPLE * chaosMultiplier() * timedMultiplier * goldenMultiplier;

  // The event for this apple is rolled after it has been scored.
  const event = rollEvent(state.eventRand, state.eaten);
  state.chain.push(eventCode(event));
  applyEvent(event);
  syncApples();
}

let lastTick = 0;
function frame(now) {
  if (state.over) return;
  expireTimed(now);
  if (now < state.pausedUntil) {
    // Frozen mid-run while the player takes in what just changed. Keep
    // lastTick level with now so the snake doesn't lurch forward on resume.
    lastTick = now;
  } else if (now - lastTick >= tickInterval()) {
    lastTick = now;
    step();
  }
  draw();
  updateHud();
  requestAnimationFrame(frame);
}

// --- rendering -------------------------------------------------------

function draw() {
  const cell = canvas.width / GRID;
  ctx.fillStyle = '#0f1115';
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  ctx.save();
  if (mirrored()) {
    ctx.translate(canvas.width, 0);
    ctx.scale(-1, 1);
  }

  ctx.fillStyle = '#2b2f3a';
  for (const w of state.walls) ctx.fillRect(w.x * cell, w.y * cell, cell, cell);

  const blink = has('ghost') && Math.floor(performance.now() / 350) % 2 === 0;
  if (!blink) {
    for (const a of state.apples) {
      ctx.fillStyle = state.golden ? '#ffd23f' : '#ff4d4d';
      ctx.beginPath();
      ctx.arc(a.x * cell + cell / 2, a.y * cell + cell / 2, cell * 0.36, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  state.snake.forEach((s, i) => {
    ctx.fillStyle = i === 0 ? '#7ee787' : '#3fb950';
    ctx.fillRect(s.x * cell + 1, s.y * cell + 1, cell - 2, cell - 2);
  });

  if (has('dark')) {
    const head = state.snake[0];
    const gradient = ctx.createRadialGradient(
      head.x * cell + cell / 2, head.y * cell + cell / 2, cell * 1.5,
      head.x * cell + cell / 2, head.y * cell + cell / 2, cell * 5,
    );
    gradient.addColorStop(0, 'rgba(15,17,21,0)');
    gradient.addColorStop(1, 'rgba(15,17,21,0.97)');
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, canvas.width, canvas.height);
  }

  ctx.restore();
}

function updateHud() {
  els.apples.textContent = `🍎 ${state.eaten}`;
  els.score.textContent = `${Math.round(state.score)}`;
  const active = [...state.permanent, ...state.timed.map((t) => t.id)];
  els.mods.textContent = active.length ? `⚡ ${active.length}` : '';
}

// --- input -----------------------------------------------------------

function turn(dx, dy) {
  if (timedActive('invert')) { dx = -dx; dy = -dy; }
  if (mirrored()) dx = -dx;
  if (state.dir.x === -dx && state.dir.y === -dy) return;  // no instant U-turn
  state.queuedDir = { x: dx, y: dy };
}

const KEYS = {
  ArrowUp: [0, -1], ArrowDown: [0, 1], ArrowLeft: [-1, 0], ArrowRight: [1, 0],
  w: [0, -1], s: [0, 1], a: [-1, 0], d: [1, 0],
};
window.addEventListener('keydown', (e) => {
  const move = KEYS[e.key];
  if (move && state && !state.over) { e.preventDefault(); turn(move[0], move[1]); }
});

// On-screen buttons. Telegram treats a vertical drag as "pull the Mini App
// closed", so a swipe can never be fully relied on — these always work.
document.getElementById('pad').addEventListener('pointerdown', (e) => {
  const dir = e.target.dataset?.dir;
  if (!dir || !state || state.over) return;
  e.preventDefault();
  const moves = { up: [0, -1], down: [0, 1], left: [-1, 0], right: [1, 0] };
  turn(...moves[dir]);
});

let touchStart = null;
canvas.addEventListener('touchstart', (e) => {
  touchStart = { x: e.touches[0].clientX, y: e.touches[0].clientY };
}, { passive: true });

// Must be non-passive: swallowing the move is what stops the gesture from
// reaching Telegram and dragging the sheet down mid-game.
canvas.addEventListener('touchmove', (e) => e.preventDefault(), { passive: false });

canvas.addEventListener('touchend', (e) => {
  if (!touchStart || !state || state.over) return;
  const dx = e.changedTouches[0].clientX - touchStart.x;
  const dy = e.changedTouches[0].clientY - touchStart.y;
  if (Math.abs(dx) < 18 && Math.abs(dy) < 18) return;
  if (Math.abs(dx) > Math.abs(dy)) turn(Math.sign(dx), 0);
  else turn(0, Math.sign(dy));
  touchStart = null;
}, { passive: true });

// --- game over -------------------------------------------------------

function gameOver() {
  state.over = true;
  const cleared = state.eaten >= APPLES_TO_CLEAR_DAY;
  els.overTitle.textContent = cleared ? '🏁 День пройден' : '💀 Конец';
  els.overStats.innerHTML = `
    <div class="big">${Math.round(state.score)}</div>
    <div class="muted">очков · 🍎 ${state.eaten} ·
      ${cleared ? 'день засчитан' : `до зачёта ${APPLES_TO_CLEAR_DAY - state.eaten} 🍎`}</div>`;
  els.over.classList.add('show');
}

function payload() {
  return JSON.stringify({
    v: 1,
    day: today,
    apples: state.eaten,
    score: Math.round(state.score),
    ms: Math.round(performance.now() - state.startedAt),
    events: state.chain,
  });
}

els.send.addEventListener('click', () => {
  if (!tg) return;
  tg.sendData(payload());  // Telegram closes the app right after this
});

els.again.addEventListener('click', () => {
  els.over.classList.remove('show');
  start();
});

els.play.addEventListener('click', () => {
  els.start.classList.remove('show');
  start();
});

// Test seam: lets an end-to-end check pull the exact payload the bot will
// receive and run it through services/chaos/validate.py.
window.__chaosPayload = payload;

// --- boot ------------------------------------------------------------

function resize() {
  // Leaves room for the header, the HUD and the control pad below the board.
  const size = Math.min(window.innerWidth - 24, window.innerHeight - 330, 460);
  const dpr = window.devicePixelRatio || 1;
  canvas.style.width = `${size}px`;
  canvas.style.height = `${size}px`;
  canvas.width = Math.round(size * dpr);
  canvas.height = Math.round(size * dpr);
}
window.addEventListener('resize', resize);

function start() {
  state = freshState();
  syncApples();
  lastTick = performance.now();
  requestAnimationFrame(frame);
}

async function boot() {
  tg?.ready();
  tg?.expand();
  // Bot API 7.7+. Without it a downward swipe closes the app instead of
  // steering the snake. Older clients fall back to the buttons below.
  if (typeof tg?.disableVerticalSwipes === 'function') tg.disableVerticalSwipes();
  today = dayKey();
  daySeed = await seedForDay(today);
  els.day.textContent = today;
  els.send.style.display = tg ? '' : 'none';
  resize();
  // Deliberately no auto-start: the run counts towards the day, and
  // beginning it before the player has even looked at the screen is a
  // good way to lose one.
}

boot();
