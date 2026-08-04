// Day seed, PRNG and the event catalogue.
//
// This file is the JavaScript half of a pair: services/chaos/seed.py and
// services/chaos/events.py on the bot are the other half. The bot replays
// the day's event chain to check that a submitted run really played today's
// game, so the two must agree exactly — same PRNG, same rarity ladder, same
// event order within each rarity. tests/test_chaos_seed.py pins the PRNG
// against vectors generated with node.

export const MASK32 = 0xffffffff;

// Must match CHAOS_SALT on the bot. Not a secret — the client is public
// source — it only keeps the seed from being guessable from the date alone.
export const SALT = 'chaos-chain';

const TZ_OFFSET_HOURS = 5;   // Almaty
const DAY_START_HOUR = 12;   // the game day starts at noon, not midnight

export function mulberry32(a) {
  return function () {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function dayKey(now = new Date()) {
  // now + 5h - 12h == now - 7h, then read off the UTC date.
  const shifted = new Date(now.getTime() + (TZ_OFFSET_HOURS - DAY_START_HOUR) * 3600_000);
  return shifted.toISOString().slice(0, 10);
}

export async function seedForDay(key) {
  const bytes = new TextEncoder().encode(key + SALT);
  const digest = new Uint8Array(await crypto.subtle.digest('SHA-256', bytes));
  // Python takes hexdigest[:8], i.e. the first four bytes, big-endian.
  return ((digest[0] << 24) | (digest[1] << 16) | (digest[2] << 8) | digest[3]) >>> 0;
}

export const COMMON = 'common';
export const RARE = 'rare';
export const EPIC = 'epic';
export const LEGENDARY = 'legendary';
export const RARITY_ORDER = [COMMON, RARE, EPIC, LEGENDARY];

export const RARITY_PREFIX = { [COMMON]: 'c', [RARE]: 'r', [EPIC]: 'e', [LEGENDARY]: 'l' };
export const RARITY_LABEL = { [COMMON]: '🟢', [RARE]: '🔵', [EPIC]: '🟣', [LEGENDARY]: '🟡' };

export const PERMANENT = 'permanent';
export const TIMED = 'timed';
export const INSTANT = 'instant';

export const MAX_PERMANENT_MODIFIERS = 4;
export const BASE_POINTS_PER_APPLE = 10;
export const CHAOS_BONUS_PER_MODIFIER = 0.15;
export const APPLES_TO_CLEAR_DAY = 7;

// (applies while applesEaten <= n, weights); null = "and beyond"
export const RARITY_LADDER = [
  [2, { common: 90, rare: 10, epic: 0, legendary: 0 }],
  [4, { common: 65, rare: 28, epic: 7, legendary: 0 }],
  [6, { common: 45, rare: 35, epic: 18, legendary: 2 }],
  [null, { common: 25, rare: 40, epic: 30, legendary: 5 }],
];

// Bumped whenever the catalogue below changes. The client sends it with the
// result so the bot can tell "this player is running a cached copy of an
// older game" apart from "this chain is forged" — a browser will serve
// yesterday's JavaScript for a while after a deploy.
export const CATALOGUE_VERSION = 2;

// ORDER MATTERS. The pick within a rarity is an index into these arrays, so
// reordering an entry silently changes every future day's chain and breaks
// validation on the bot. Append, never insert.
export const EVENTS = [
  { id: 'speed', rarity: COMMON, kind: PERMANENT, title: 'Разгон', text: 'Скорость +20%' },
  { id: 'walls', rarity: COMMON, kind: PERMANENT, title: 'Стены', text: 'На поле появились три блока' },
  { id: 'invert', rarity: COMMON, kind: TIMED, duration: 10, title: 'Инверсия', text: 'Управление наоборот' },
  { id: 'ghost', rarity: COMMON, kind: PERMANENT, title: 'Призрак', text: 'Яблоко мигает' },
  { id: 'growth', rarity: COMMON, kind: INSTANT, title: 'Отъедание', text: '+2 сегмента к длине' },
  { id: 'wander', rarity: COMMON, kind: PERMANENT, title: 'Блуждание', text: 'Яблоко не стоит на месте' },

  { id: 'portal', rarity: RARE, kind: PERMANENT, title: 'Портал', text: 'Края поля переключились' },
  { id: 'double', rarity: RARE, kind: TIMED, duration: 15, multiplier: 2, title: 'Двойные очки', text: '×2 к очкам' },
  { id: 'mirror', rarity: RARE, kind: PERMANENT, title: 'Зеркало', text: 'Поле отразилось' },
  { id: 'shed', rarity: RARE, kind: INSTANT, title: 'Линька', text: 'Сбросил половину длины' },

  { id: 'dark', rarity: EPIC, kind: PERMANENT, title: 'Темнота', text: 'Видно только вокруг головы' },
  { id: 'golden', rarity: EPIC, kind: INSTANT, multiplier: 5, title: 'Золотое яблоко', text: 'Следующее яблоко ×5' },
  { id: 'twins', rarity: EPIC, kind: PERMANENT, title: 'Двойня', text: 'На поле два яблока' },
  { id: 'slow', rarity: EPIC, kind: TIMED, duration: 15, title: 'Замедление', text: 'Время загустело' },

  { id: 'reverse', rarity: LEGENDARY, kind: TIMED, duration: 20, title: 'Обратный ход', text: 'Хвост стал головой' },
  { id: 'swarm', rarity: LEGENDARY, kind: TIMED, duration: 15, title: 'Нашествие', text: 'Пять яблок разом' },
  { id: 'goldrush', rarity: LEGENDARY, kind: TIMED, duration: 20, multiplier: 5, title: 'Золотая лихорадка', text: 'Каждое яблоко ×5' },
];

export const EVENTS_BY_RARITY = RARITY_ORDER.reduce((acc, rarity) => {
  acc[rarity] = EVENTS.filter((e) => e.rarity === rarity);
  return acc;
}, {});

export function weightsFor(applesEaten) {
  for (const [threshold, weights] of RARITY_LADDER) {
    if (threshold === null || applesEaten <= threshold) return weights;
  }
  return RARITY_LADDER[RARITY_LADDER.length - 1][1];
}

export function pickRarity(roll, applesEaten) {
  const weights = weightsFor(applesEaten);
  const total = RARITY_ORDER.reduce((sum, r) => sum + weights[r], 0);
  let cumulative = 0;
  const target = roll * total;
  for (const rarity of RARITY_ORDER) {
    cumulative += weights[rarity];
    if (target < cumulative) return rarity;
  }
  return COMMON;
}

// Consumes exactly two numbers — the Python side depends on that count.
export function rollEvent(rand, applesEaten) {
  const rarity = pickRarity(rand(), applesEaten);
  const pool = EVENTS_BY_RARITY[rarity];
  return pool[Math.floor(rand() * pool.length) % pool.length];
}

export function eventCode(event) {
  return `${RARITY_PREFIX[event.rarity]}:${event.id}`;
}
