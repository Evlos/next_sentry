/* WCAG contrast audit for the token pairs the UI actually renders.
   Reads the tokens straight out of src/app.css so the audit and the
   stylesheet can never drift apart.
   Run: node scripts/check-contrast.mjs
   Exits non-zero if any text pair misses its target ratio. */
import { readFileSync } from 'node:fs';

const css = readFileSync(new URL('../src/app.css', import.meta.url), 'utf8');

/* Pull the tokens out of the :root block and the .dark block. The names
   the UI uses (muted, faint, error…) are mapped onto the custom-property
   names in the stylesheet, so the audit talks about the same vocabulary
   the templates do. */
const ALIAS = {
  'ink-2': 'muted',
  'ink-3': 'faint',
  'line-soft': 'line-soft',
};

function tokens(selector) {
  const start = css.indexOf(selector + ' {');
  if (start < 0) throw new Error(`no ${selector} block in src/app.css`);
  const body = css.slice(start, css.indexOf('}', start));
  const out = {};
  const expand = (h) => (h.length === 4 ? '#' + [...h.slice(1)].map((c) => c + c).join('') : h);
  for (const m of body.matchAll(/--c-([a-z0-9-]+):\s*(#[0-9a-f]{3,8})\s*;/gi)) {
    out[ALIAS[m[1]] ?? m[1]] = expand(m[2]);
  }
  for (const m of body.matchAll(/--l-([a-z]+):\s*(#[0-9a-f]{3,8})\s*;/gi)) {
    out[m[1]] = expand(m[2]);
  }
  return out;
}

const THEMES = { light: tokens(':root'), dark: tokens('.dark') };

for (const [name, t] of Object.entries(THEMES)) {
  for (const lvl of ['fatal', 'error', 'warning', 'info', 'debug']) {
    if (!t[lvl]) throw new Error(`${name}: --l-${lvl} not found in src/app.css`);
  }
}

const L = (hex) => {
  const n = hex.replace('#', '');
  const v = [0, 2, 4].map((i) => parseInt(n.slice(i, i + 2), 16) / 255);
  const lin = v.map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2];
};
const ratio = (a, b) => {
  const [x, y] = [L(a), L(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
};

/* [foreground, background, minimum, what it is] — 3.0 is the AA floor for
   large text and for text that is duplicated elsewhere on the page. */
const PAIRS = [
  ['ink', 'canvas', 4.5, 'body text on canvas'],
  ['ink', 'surface', 4.5, 'body text on a panel'],
  ['ink', 'raised', 4.5, 'body text on a groove'],
  ['muted', 'canvas', 4.5, 'secondary text on canvas'],
  ['muted', 'surface', 4.5, 'secondary text on a panel'],
  ['muted', 'raised', 4.5, 'secondary text on a groove'],
  ['faint', 'canvas', 4.5, 'labels, timestamps, line numbers'],
  ['faint', 'surface', 4.5, 'labels on a panel'],
  ['faint', 'raised', 4.5, 'line numbers on a groove'],
  ['accent', 'canvas', 4.5, 'links'],
  ['accent', 'surface', 4.5, 'links on a panel'],
  ['error', 'surface', 4.5, 'error level word'],
  ['error', 'raised', 4.5, 'error level word on a groove'],
  ['warning', 'surface', 4.5, 'warning level word'],
  ['warning', 'raised', 4.5, 'warning level word on a groove'],
  ['info', 'surface', 4.5, 'info level word'],
  ['info', 'raised', 4.5, 'info level word on a groove'],
  ['debug', 'surface', 3.0, 'debug level word (deliberately quiet)'],
  ['debug', 'raised', 3.0, 'debug level word on a groove'],
  ['fatal', 'surface', 4.5, 'fatal level word'],
  ['fatal', 'raised', 4.5, 'fatal level word on a groove'],
  ['faint', 'canvas', 3.0, 'footer / quiet meta'],
];

let failed = 0;
for (const [name, t] of Object.entries(THEMES)) {
  console.log(`\n── ${name} ${'─'.repeat(52)}`);
  for (const [fg, bg, min, what] of PAIRS) {
    const r = ratio(t[fg], t[bg]);
    const ok = r >= min;
    if (!ok) failed++;
    console.log(
      `  ${ok ? '  ok ' : 'FAIL '} ${r.toFixed(2).padStart(5)}:1  (need ${min})  ${fg} on ${bg} — ${what}`
    );
  }
}
console.log(failed ? `\n${failed} pair(s) below target\n` : '\nall pairs pass\n');
process.exit(failed ? 1 : 0);
