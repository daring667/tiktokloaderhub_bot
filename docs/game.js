// Snake, plus the chaos that lands on it after every apple.

// The ?v= on the imports is not decoration. A browser will keep a cached
// chaos.js while fetching a fresh game.js, and the module then fails outright
// — "does not provide an export named ..." — leaving a blank screen rather
// than a merely outdated game. Bump it whenever chaos.js or merge.js changes;
// keeping it equal to CATALOGUE_VERSION is the easiest way to remember.
import {
  APPLES_TO_CLEAR_DAY, BASE_POINTS_PER_APPLE, CHAOS_BONUS_PER_MODIFIER,
  MAX_PERMANENT_MODIFIERS, PERMANENT, TIMED, RARITY_LABEL, CATALOGUE_VERSION,
  dayKey, eventCode, mulberry32, rollEvent, seedForDay,
} from './chaos.js?v=2';
import { MergeStage, MERGE_TARGET, drawMerge, pickMergeMod } from './merge.js?v=2';

const GRID = 18;
const BASE_TICK_MS = 150;
const SPEED_STEP = 1.2;
const WANDER_EVERY_MS = 2600;

// Only these two put everything somewhere else, and only after them does a
// player need a beat to re-read the board. Pausing on every apple broke the
// run into stutters at exactly the moments it was going well — worse than the
// disorientation it was meant to fix.
const REORIENTING_EVENTS = new Set(['mirror', 'reverse']);
const EVENT_PAUSE_MS = 550;

// One turn may wait behind the one being applied. A single slot meant two
// quick taps overwrote each other and the second was silently dropped; a
// deeper queue would keep turning after the player stopped pressing.
const MAX_QUEUED_TURNS = 2;

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
  chain: document.getElementById('chain'),
  chainStats: document.getElementById('chain-stats'),
  next: document.getElementById('next'),
  stop: document.getElementById('stop'),
};

let state = null;
let today = dayKey();
let daySeed = 0;

// The chain. Snake is always the first link; clearing it opens the next.
// `stages` accumulates what gets sent to the bot at the end.
let phase = 'snake';        // 'snake' | 'merge'
let merge = null;
let mergeMod = null;        // the whole day shares one, drawn from the seed
let mergeStartedAt = 0;
let stages = [];

/** A fresh uint32 for anything that should differ between attempts. */
function runSeed() {
  if (window.crypto?.getRandomValues) {
    return window.crypto.getRandomValues(new Uint32Array(1))[0];
  }
  return (Math.random() * 4294967296) >>> 0;
}

function freshState() {
  return {
    snake: [{ x: 9, y: 9 }, { x: 8, y: 9 }, { x: 7, y: 9 }],
    dir: { x: 1, y: 0 },
    turns: [],              // pending direction changes, oldest first
    apples: [],
    walls: [],
    permanent: [],          // event ids, oldest first
    timed: [],              // { id, until, multiplier }
    golden: false,
    pausedUntil: 0,
    wanderedAt: 0,
    score: 0,
    eaten: 0,
    chain: [],
    startedAt: performance.now(),
    over: false,
    // Two streams, seeded on purpose from different things.
    //
    // Events come from the day: everyone must meet the same chain in the
    // same order, and the bot replays it to check a submitted run. Exactly
    // two draws per apple — anything else drawing from here would shift it.
    //
    // The world — where apples and walls land — is seeded per run. Tying it
    // to the day meant every attempt repeated the same layout, so the way to
    // climb the leaderboard was to memorise a route rather than play well.
    eventRand: mulberry32(daySeed),
    worldRand: mulberry32(runSeed()),
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
  // "Замедление" is the one event that helps — which is what makes rolling
  // an epic feel like a reward rather than another tax.
  const relief = timedActive('slow') ? 2 : 1;
  return (BASE_TICK_MS / speedFactor()) * relief;
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

function appleTarget() {
  if (timedActive('swarm')) return 5;
  return has('twins') ? 2 : 1;
}

function syncApples() {
  const wanted = appleTarget();
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
  } else if (event.id === 'shed') {
    // Never below the starting length, or it stops reading as a snake.
    state.snake.length = Math.max(3, Math.ceil(state.snake.length / 2));
  } else if (event.id === 'golden') {
    state.golden = true;
  }

  showToast(event);

  if (REORIENTING_EVENTS.has(event.id)) {
    state.pausedUntil = performance.now() + EVENT_PAUSE_MS;
    // A turn queued a moment before the board flipped was aimed at the old
    // layout; carrying it over would steer somewhere never meant.
    state.turns.length = 0;
  }
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
  // One queued turn per tick, so a burst of taps is played back in order
  // instead of the last one winning.
  if (state.turns.length) state.dir = state.turns.shift();

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

  // "Нашествие" ends by putting the extra apples away again.
  if (state.apples.length !== appleTarget()) syncApples();

  // "Блуждание": the apple refuses to wait where you left it.
  if (has('wander') && now - state.wanderedAt > WANDER_EVERY_MS) {
    state.wanderedAt = now;
    state.apples = state.apples.map(() => freeCell());
  }

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
  if (phase === 'merge') {
    els.score.textContent = `${totalScore() + (merge ? merge.score : 0)}`;
    els.mods.textContent = merge ? `цель ${MERGE_TARGET} · ${merge.best}` : '';
    return;
  }
  els.apples.textContent = `🍎 ${state.eaten}`;
  els.score.textContent = `${Math.round(state.score)}`;
  const active = [...state.permanent, ...state.timed.map((t) => t.id)];
  els.mods.textContent = active.length ? `⚡ ${active.length}` : '';
}

// --- input -----------------------------------------------------------

function turn(dx, dy) {
  if (timedActive('invert')) { dx = -dx; dy = -dy; }
  if (mirrored()) dx = -dx;

  // Validate against the last direction already accepted, not against the
  // one currently being travelled. Comparing with state.dir threw away the
  // second half of a two-step turn like right → down → left, which is what
  // made the pad feel like it was dropping presses.
  const previous = state.turns.length ? state.turns[state.turns.length - 1] : state.dir;
  if (previous.x === -dx && previous.y === -dy) return;   // no instant U-turn
  if (previous.x === dx && previous.y === dy) return;     // already going there

  if (state.turns.length >= MAX_QUEUED_TURNS) return;
  state.turns.push({ x: dx, y: dy });
  tg?.HapticFeedback?.impactOccurred?.('light');
}

const DIR_NAME = { '0,-1': 'up', '0,1': 'down', '-1,0': 'left', '1,0': 'right' };

/** Routes one directional input to whichever link of the chain is running. */
function steer(dx, dy) {
  if (phase === 'merge') {
    if (!merge || merge.over) return;
    merge.move(DIR_NAME[`${dx},${dy}`]);
    drawMerge(ctx, canvas.width, merge);
    updateHud();
    if (merge.over || merge.cleared) endMerge();
    return;
  }
  if (!state || state.over) return;
  turn(dx, dy);
}

const KEYS = {
  ArrowUp: [0, -1], ArrowDown: [0, 1], ArrowLeft: [-1, 0], ArrowRight: [1, 0],
  w: [0, -1], s: [0, 1], a: [-1, 0], d: [1, 0],
};
window.addEventListener('keydown', (e) => {
  const move = KEYS[e.key];
  if (move) { e.preventDefault(); steer(move[0], move[1]); }
});

// On-screen buttons. Telegram treats a vertical drag as "pull the Mini App
// closed", so a swipe can never be fully relied on — these always work.
document.getElementById('pad').addEventListener('pointerdown', (e) => {
  const dir = e.target.dataset?.dir;
  if (!dir) return;
  e.preventDefault();
  const moves = { up: [0, -1], down: [0, 1], left: [-1, 0], right: [1, 0] };
  steer(...moves[dir]);
});

let touchStart = null;
canvas.addEventListener('touchstart', (e) => {
  touchStart = { x: e.touches[0].clientX, y: e.touches[0].clientY };
}, { passive: true });

// Must be non-passive: swallowing the move is what stops the gesture from
// reaching Telegram and dragging the sheet down mid-game.
canvas.addEventListener('touchmove', (e) => e.preventDefault(), { passive: false });

canvas.addEventListener('touchend', (e) => {
  if (!touchStart) return;
  const dx = e.changedTouches[0].clientX - touchStart.x;
  const dy = e.changedTouches[0].clientY - touchStart.y;
  if (Math.abs(dx) < 18 && Math.abs(dy) < 18) return;
  if (Math.abs(dx) > Math.abs(dy)) steer(Math.sign(dx), 0);
  else steer(0, Math.sign(dy));
  touchStart = null;
}, { passive: true });

// --- game over -------------------------------------------------------

function gameOver() {
  state.over = true;
  const cleared = state.eaten >= APPLES_TO_CLEAR_DAY;

  stages.push({
    g: 'snake',
    apples: state.eaten,
    score: Math.round(state.score),
    ms: Math.round(performance.now() - state.startedAt),
    events: state.chain,
  });

  if (cleared) {
    // The chain opens. The snake score is banked either way, so moving on
    // can only add to the day.
    els.chainStats.innerHTML = `
      <div class="big">${Math.round(state.score)}</div>
      <div class="muted">очков за змейку · 🍎 ${state.eaten}<br><br>
        Следующее звено — <b>Слияние</b>.<br>
        Сложи плитку <b>${MERGE_TARGET}</b>, чтобы пройти цепочку.<br>
        Модификатор дня: <b>${mergeMod.title}</b> — ${mergeMod.text.toLowerCase()}</div>`;
    els.chain.classList.add('show');
    return;
  }

  showFinal('💀 Конец', `до зачёта ${APPLES_TO_CLEAR_DAY - state.eaten} 🍎`);
}

function startMerge() {
  // Stop the snake loop outright rather than trusting the caller to have
  // done it: if it keeps running it repaints the board every frame and the
  // merge grid is never visible.
  if (state) state.over = true;
  phase = 'merge';
  // Same split as the snake: the modifier is the day's and is checked by the
  // bot, but the tile spawns are this attempt's, so replaying the day isn't
  // a matter of remembering which tile comes next.
  merge = new MergeStage(mulberry32(runSeed()), mergeMod);
  mergeStartedAt = performance.now();
  els.apples.textContent = `🔗 ${mergeMod.title}`;
  drawMerge(ctx, canvas.width, merge);
  updateHud();
}

function endMerge() {
  stages.push({
    g: 'merge',
    score: merge.score,
    best: merge.best,
    moves: merge.moves,
    ms: Math.round(performance.now() - mergeStartedAt),
    mod: mergeMod.id,
    cleared: merge.cleared,
  });
  showFinal(
    merge.cleared ? '🔗 Цепочка пройдена' : '🏁 День засчитан',
    merge.cleared ? `собрана плитка ${merge.best}` : `слияние: дошёл до ${merge.best}`,
  );
}

function showFinal(title, subtitle) {
  els.overTitle.textContent = title;
  els.overStats.innerHTML = `
    <div class="big">${totalScore()}</div>
    <div class="muted">очков за день · ${subtitle}</div>`;
  els.over.classList.add('show');
}

const totalScore = () => stages.reduce((sum, s) => sum + s.score, 0);

function payload() {
  return JSON.stringify({
    v: 2,
    cat: CATALOGUE_VERSION,
    day: today,
    score: totalScore(),
    ms: stages.reduce((sum, s) => sum + s.ms, 0),
    stages,
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

els.next.addEventListener('click', () => {
  els.chain.classList.remove('show');
  startMerge();
});

els.stop.addEventListener('click', () => {
  // Banking the snake result and walking away is a legitimate choice — the
  // day is already cleared at this point.
  els.chain.classList.remove('show');
  showFinal('🏁 День засчитан', 'цепочка не пройдена');
});

// Test seam. Reaching the second link takes seven apples of competent play,
// which an automated check can't do, so it can jump there directly and then
// run the resulting payload through services/chaos/validate.py.
window.__chaosTest = {
  payload,
  steer,
  startMerge,
  phase: () => phase,
  merge: () => merge,
  state: () => state,
  stages: () => stages,
  bankSnake: (apples, score) => {
    // Replays the day's chain for `apples` apples, exactly as eating them
    // would have produced it — otherwise the bot rejects the run.
    const r = mulberry32(daySeed);
    const chain = [];
    for (let i = 0; i < apples; i++) chain.push(eventCode(rollEvent(r, i + 1)));
    stages.push({ g: 'snake', apples, score, ms: apples * 2000, events: chain });
  },
};

// --- boot ------------------------------------------------------------

function resize() {
  // Leaves room for the header, the HUD and the control pad below the board.
  // Header, HUD, the event line and the pad all take their share — but the
  // result has to stay positive. On a short viewport the subtraction went
  // negative, the browser threw the invalid width away, and the canvas
  // silently fell back to its 300x150 default: a board that is no longer
  // square and no longer matches what the game thinks it is drawing.
  const available = Math.min(window.innerWidth - 24, window.innerHeight - 398, 460);
  const size = Math.max(200, available);
  const dpr = window.devicePixelRatio || 1;
  canvas.style.width = `${size}px`;
  canvas.style.height = `${size}px`;
  canvas.width = Math.round(size * dpr);
  canvas.height = Math.round(size * dpr);
}
window.addEventListener('resize', resize);

function start() {
  phase = 'snake';
  merge = null;
  stages = [];
  state = freshState();
  syncApples();
  els.apples.textContent = '🍎 0';
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
  // Its own stream, so drawing it can never shift the snake event chain the
  // bot replays.
  mergeMod = pickMergeMod(mulberry32((daySeed ^ 0x27d4eb2f) >>> 0));
  els.day.textContent = today;
  els.send.style.display = tg ? '' : 'none';
  resize();
  // Deliberately no auto-start: the run counts towards the day, and
  // beginning it before the player has even looked at the screen is a
  // good way to lose one.
}

boot();
