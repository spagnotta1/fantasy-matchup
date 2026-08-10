/**
 * Design-token contrast audit.
 *
 * Parses the token blocks straight out of `src/styles/index.css` and checks
 * every foreground/background pairing the UI actually draws, in both themes.
 * Reading the stylesheet rather than a copied table is the point: a hardcoded
 * palette in the test drifts from the one that ships, and a contrast test that
 * has drifted is worse than none.
 *
 * Colours resolve through a real browser canvas. Chromium returns oklch()
 * verbatim from getComputedStyle, so parsing that gives back the authored
 * coordinates rather than sRGB; painting a pixel forces the true conversion,
 * including gamut mapping.
 *
 * Exits non-zero on any failure, and prints the smallest lightness that would
 * fix each one — hue and chroma held fixed, because the palette was chosen
 * deliberately and the job is to make it legal, not to repick it.
 *
 *   node tests/e2e/token-contrast.mjs
 */
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { chromium } from '@playwright/test'

const cssPath = fileURLToPath(new URL('../../src/styles/index.css', import.meta.url))
const css = readFileSync(cssPath, 'utf8')

/** Pulls `--app-*` declarations out of one brace-delimited block. */
function tokensFrom(block) {
  const out = {}
  for (const m of block.matchAll(/--app-([\w-]+):\s*([^;]+);/g)) {
    const value = m[2].trim()
    // Shadows and other multi-part values are not colours.
    if (/^oklch\([^)]*\)$/.test(value)) out[m[1]] = value
  }
  return out
}

// `:root { ... }` is the light theme — the first block, up to the first close.
const lightBlock = css.slice(css.indexOf(':root {'), css.indexOf('\n}', css.indexOf(':root {')))
// The dark theme under the media query.
const darkStart = css.indexOf("@media (prefers-color-scheme: dark)")
const darkBlock = css.slice(darkStart, css.indexOf('\n  }', darkStart))

const THEMES = [
  ['LIGHT', tokensFrom(lightBlock)],
  ['DARK', tokensFrom(darkBlock)],
]

/**
 * Pairings the UI actually renders, with the threshold each one owes.
 * 4.5 for body text, 3.0 for large text and for non-text indicators.
 */
const PAIRS = [
  ['text', 'surface', 4.5],
  ['text', 'bg', 4.5],
  ['text', 'surface-sunken', 4.5],
  ['text-secondary', 'surface', 4.5],
  ['text-secondary', 'bg', 4.5],
  ['text-secondary', 'surface-sunken', 4.5],
  ['text-muted', 'surface', 4.5],
  ['text-muted', 'bg', 4.5],
  ['text-muted', 'surface-sunken', 4.5],
  ['text-inverted', 'accent', 4.5],
  ['on-accent', 'accent', 4.5],
  ['on-accent', 'accent-hover', 4.5],
  ['accent-text', 'accent-soft', 4.5],
  ['accent-text', 'surface', 4.5],
  ['positive-text', 'positive-soft', 4.5],
  ['positive-text', 'surface', 4.5],
  ['negative-text', 'negative-soft', 4.5],
  ['negative-text', 'surface', 4.5],
  ['caution-text', 'caution-soft', 4.5],
  ['caution-text', 'surface', 4.5],
  ['info-text', 'info-soft', 4.5],
  ['info-text', 'surface', 4.5],
  // Non-text: meter fills, dots, chart marks, borders that carry meaning.
  ['accent', 'surface', 3.0],
  ['positive', 'surface', 3.0],
  ['negative', 'surface', 3.0],
  ['caution', 'surface', 3.0],
  ['info', 'surface', 3.0],
  // The resting border of an input, select or secondary button — the line that
  // identifies the control, which is what 1.4.11 is about. `border-strong` is
  // deliberately NOT checked: it appears only behind `hover:`, and a hover
  // enhancement is not what identifies a control.
  ['border-input', 'surface', 3.0],
]

const browser = await chromium.launch()
const page = await browser.newPage()
await page.setContent('<html><body></body></html>')
await page.evaluate(() => {
  window.ctx = document.createElement('canvas').getContext('2d', { willReadFrequently: true })
  window.toRgb = (c) => {
    window.ctx.fillStyle = '#000'
    window.ctx.fillStyle = c
    window.ctx.fillRect(0, 0, 1, 1)
    const d = window.ctx.getImageData(0, 0, 1, 1).data
    return [d[0], d[1], d[2]]
  }
  window.lum = (rgb) => {
    const f = rgb.map((v) => {
      v /= 255
      return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4)
    })
    return 0.2126 * f[0] + 0.7152 * f[1] + 0.0722 * f[2]
  }
  window.ratio = (a, b) => {
    const la = window.lum(window.toRgb(a))
    const lb = window.lum(window.toRgb(b))
    return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05)
  }
  window.hex = (c) => '#' + window.toRgb(c).map((v) => v.toString(16).padStart(2, '0')).join('')
})

const ratio = (a, b) => page.evaluate(([x, y]) => window.ratio(x, y), [a, b])
const hex = (c) => page.evaluate((x) => window.hex(x), c)

/**
 * Smallest lightness change that clears `need`, moving whichever side can
 * actually move. A near-white foreground cannot get lighter, so for those the
 * background is the one that has to give.
 */
async function suggest(fgCss, bgCss, need) {
  for (const [label, subject, other] of [
    ['fg', fgCss, bgCss],
    ['bg', bgCss, fgCss],
  ]) {
    const m = subject.match(/oklch\(([\d.]+)%\s+([\d.]+)\s+([\d.]+)\s*\)/)
    if (!m) continue
    const [, l0, c, h] = m
    const subjectLum = await page.evaluate((x) => window.lum(window.toRgb(x)), subject)
    const otherLum = await page.evaluate((x) => window.lum(window.toRgb(x)), other)
    const darken = subjectLum > otherLum ? false : true
    let lo = darken ? 0 : Number(l0)
    let hi = darken ? Number(l0) : 100
    let best = null
    for (let i = 0; i < 30; i++) {
      const mid = (lo + hi) / 2
      const cand = `oklch(${mid.toFixed(1)}% ${c} ${h})`
      const rr = await ratio(cand, other)
      if (rr >= need) {
        best = { css: cand, r: rr }
        if (darken) lo = mid
        else hi = mid
      } else if (darken) hi = mid
      else lo = mid
    }
    if (best) return `${label} -> ${best.css} (${best.r.toFixed(2)}:1)`
  }
  return 'no single-channel lightness fix; repick the pair'
}

let failures = 0

for (const [themeName, tokens] of THEMES) {
  console.log(`\n${'='.repeat(74)}\n${themeName}  (${Object.keys(tokens).length} colour tokens)\n${'='.repeat(74)}`)

  for (const [fg, bg, need] of PAIRS) {
    if (!(fg in tokens) || !(bg in tokens)) continue
    const r = await ratio(tokens[fg], tokens[bg])
    const ok = r >= need
    if (!ok) failures++
    const line = `${ok ? 'PASS' : 'FAIL'}  ${`${fg} on ${bg}`.padEnd(38)} ${r.toFixed(2).padStart(5)}:1 (need ${need})  ${await hex(tokens[fg])}/${await hex(tokens[bg])}`
    console.log(ok ? line : `${line}\n      ${await suggest(tokens[fg], tokens[bg], need)}`)
  }
}

await browser.close()

console.log(`\n${failures === 0 ? 'All token pairings meet WCAG AA.' : `${failures} failing pairing(s).`}`)
process.exit(failures === 0 ? 0 : 1)
