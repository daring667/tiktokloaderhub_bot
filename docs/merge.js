// "Слияние" — the second link in the chain: slide tiles, equal ones merge.
//
// Deliberately a different kind of thinking from snake: no reflexes, all
// planning. It reuses the on-screen pad, which maps onto the four slide
// directions exactly.
//
// Tile spawns come from a stream of their own so they can never disturb the
// snake event stream, which the bot replays to validate a run.

export const MERGE_TARGET = 128;
export const SIZE = 4;

export const MERGE_MODS = [
  { id: 'twoSpawns', title: 'Двойной посев', text: 'После хода появляются две плитки' },
  { id: 'frozen', title: 'Заморозка', text: 'Одна плитка примерзает на 6 ходов' },
  { id: 'rotate', title: 'Вращение', text: 'Поле поворачивается каждые 5 ходов' },
];

const FROZEN_MOVES = 6;
const ROTATE_EVERY = 5;

// Mirrored by merge_mods_for_day() in services/chaos/events.py, which
// re-derives this to check what a submitted run claims it played.
export function pickMergeMod(rand) {
  return MERGE_MODS[Math.floor(rand() * MERGE_MODS.length) % MERGE_MODS.length];
}

export class MergeStage {
  constructor(rand, mod) {
    this.rand = rand;
    this.mod = mod;
    this.grid = Array.from({ length: SIZE }, () => new Array(SIZE).fill(0));
    this.score = 0;
    this.moves = 0;
    this.best = 0;
    this.cleared = false;
    this.over = false;
    this.frozen = null;        // {r, c, until}
    this.spawn();
    this.spawn();
  }

  freeCells() {
    const cells = [];
    for (let r = 0; r < SIZE; r++) {
      for (let c = 0; c < SIZE; c++) if (!this.grid[r][c]) cells.push({ r, c });
    }
    return cells;
  }

  spawn() {
    const cells = this.freeCells();
    if (!cells.length) return;
    const { r, c } = cells[Math.floor(this.rand() * cells.length) % cells.length];
    this.grid[r][c] = this.rand() < 0.9 ? 2 : 4;
  }

  /** Slides one row left, merging equal neighbours once each. */
  _collapse(row, frozenIndex) {
    const kept = [];
    for (let i = 0; i < row.length; i++) {
      if (i === frozenIndex) { kept.push({ v: row[i], locked: true }); continue; }
      if (row[i]) kept.push({ v: row[i], locked: false });
    }

    const out = [];
    for (let i = 0; i < kept.length; i++) {
      const cur = kept[i], next = kept[i + 1];
      if (cur && next && !cur.locked && !next.locked && cur.v === next.v) {
        const merged = cur.v * 2;
        out.push({ v: merged, locked: false });
        this.score += merged;
        this.best = Math.max(this.best, merged);
        if (merged >= MERGE_TARGET) this.cleared = true;
        i++;   // the pair is consumed
      } else {
        out.push(cur);
      }
    }

    // A locked tile keeps its column; everything else packs to the left.
    const result = new Array(SIZE).fill(0);
    let write = 0;
    for (const tile of out) {
      if (tile.locked) { result[frozenIndex] = tile.v; write = Math.max(write, frozenIndex + 1); }
      else { while (result[write]) write++; result[write] = tile.v; }
    }
    return result;
  }

  _rows(dir) {
    // Normalises any direction into "slide left" over a list of rows.
    const g = this.grid;
    if (dir === 'left') return g.map((row, r) => ({ cells: row.slice(), put: (v) => { g[r] = v; } }));
    if (dir === 'right') return g.map((row, r) => ({
      cells: row.slice().reverse(), put: (v) => { g[r] = v.slice().reverse(); },
    }));
    const cols = [];
    for (let c = 0; c < SIZE; c++) {
      const col = g.map((row) => row[c]);
      if (dir === 'up') {
        cols.push({ cells: col, put: (v) => { for (let r = 0; r < SIZE; r++) g[r][c] = v[r]; } });
      } else {
        cols.push({
          cells: col.slice().reverse(),
          put: (v) => { const rev = v.slice().reverse(); for (let r = 0; r < SIZE; r++) g[r][c] = rev[r]; },
        });
      }
    }
    return cols;
  }

  _frozenIndexFor(dir, laneIndex) {
    if (!this.frozen || this.mod.id !== 'frozen') return -1;
    const { r, c } = this.frozen;
    if (dir === 'left') return laneIndex === r ? c : -1;
    if (dir === 'right') return laneIndex === r ? SIZE - 1 - c : -1;
    if (dir === 'up') return laneIndex === c ? r : -1;
    return laneIndex === c ? SIZE - 1 - r : -1;
  }

  move(dir) {
    if (this.over) return false;
    const before = JSON.stringify(this.grid);

    this._rows(dir).forEach((lane, i) => {
      lane.put(this._collapse(lane.cells, this._frozenIndexFor(dir, i)));
    });

    if (JSON.stringify(this.grid) === before) return false;   // nothing moved

    this.moves++;
    this.spawn();
    if (this.mod.id === 'twoSpawns') this.spawn();

    if (this.mod.id === 'frozen') {
      if (!this.frozen || this.moves >= this.frozen.until) {
        const taken = [];
        for (let r = 0; r < SIZE; r++) {
          for (let c = 0; c < SIZE; c++) if (this.grid[r][c]) taken.push({ r, c });
        }
        this.frozen = taken.length
          ? { ...taken[Math.floor(this.rand() * taken.length) % taken.length],
              until: this.moves + FROZEN_MOVES }
          : null;
      }
    }

    if (this.mod.id === 'rotate' && this.moves % ROTATE_EVERY === 0) this._rotate();

    if (!this._hasMoves()) this.over = true;
    return true;
  }

  _rotate() {
    const g = this.grid;
    const out = Array.from({ length: SIZE }, () => new Array(SIZE).fill(0));
    for (let r = 0; r < SIZE; r++) {
      for (let c = 0; c < SIZE; c++) out[c][SIZE - 1 - r] = g[r][c];
    }
    this.grid = out;
    if (this.frozen) {
      const { r, c } = this.frozen;
      this.frozen = { r: c, c: SIZE - 1 - r, until: this.frozen.until };
    }
  }

  _hasMoves() {
    for (let r = 0; r < SIZE; r++) {
      for (let c = 0; c < SIZE; c++) {
        if (!this.grid[r][c]) return true;
        if (c + 1 < SIZE && this.grid[r][c] === this.grid[r][c + 1]) return true;
        if (r + 1 < SIZE && this.grid[r][c] === this.grid[r + 1][c]) return true;
      }
    }
    return false;
  }
}

const TILE_COLOURS = {
  2: '#2b3138', 4: '#33404a', 8: '#3f6b52', 16: '#3fb950',
  32: '#58a6ff', 64: '#8957e5', 128: '#ffd23f', 256: '#ff9f1c', 512: '#ff4d4d',
};

export function drawMerge(ctx, size, stage) {
  const pad = Math.round(size * 0.02);
  const cell = (size - pad * (SIZE + 1)) / SIZE;

  ctx.fillStyle = '#0f1115';
  ctx.fillRect(0, 0, size, size);
  ctx.fillStyle = '#161b22';
  ctx.fillRect(0, 0, size, size);

  for (let r = 0; r < SIZE; r++) {
    for (let c = 0; c < SIZE; c++) {
      const x = pad + c * (cell + pad);
      const y = pad + r * (cell + pad);
      const value = stage.grid[r][c];

      ctx.fillStyle = value ? (TILE_COLOURS[value] || '#ff2d55') : '#1c2128';
      ctx.beginPath();
      ctx.roundRect(x, y, cell, cell, cell * 0.14);
      ctx.fill();

      if (stage.frozen && stage.frozen.r === r && stage.frozen.c === c) {
        ctx.strokeStyle = '#8ed6ff';
        ctx.lineWidth = Math.max(2, cell * 0.05);
        ctx.stroke();
      }

      if (value) {
        ctx.fillStyle = value <= 4 ? '#8b949e' : '#0f1115';
        ctx.font = `700 ${Math.round(cell * (value >= 128 ? 0.3 : 0.36))}px -apple-system, sans-serif`;
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(String(value), x + cell / 2, y + cell / 2);
      }
    }
  }
}
