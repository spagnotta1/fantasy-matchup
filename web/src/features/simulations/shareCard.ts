import type { MatchupSimulation, TeamSimulation } from '@/api/schemas'
import { formatPercent, formatPoints, formatScoringProfile } from '@/utils/format'

/** The Open Graph size, which is also what group chats crop a preview to. */
const WIDTH = 1200
const HEIGHT = 630

/**
 * A matchup result as a picture, for the league group chat.
 *
 * Drawn on a canvas from the response and nothing else — the same five
 * percentiles per side the page draws, the same estimated win probability —
 * and it carries the page's qualifier with it, because an image travels
 * without the page around it: "an estimate from each player's projected
 * range, not a prediction". It never says who "will win".
 *
 * Colours are read from the live design tokens, so the card matches the theme
 * the reader is looking at. No library: the whole card is a few rectangles,
 * two strips and some text.
 */
export async function drawShareCard(
  result: MatchupSimulation,
  labels: { a: string; b: string },
): Promise<Blob> {
  await document.fonts.ready
  const canvas = document.createElement('canvas')
  canvas.width = WIDTH
  canvas.height = HEIGHT
  const ctx = canvas.getContext('2d')
  if (!ctx) throw new Error('Canvas is unavailable')

  const token = (name: string) =>
    getComputedStyle(document.documentElement).getPropertyValue(`--app-${name}`).trim()
  const font = (weight: number, size: number) =>
    `${weight} ${size}px 'Commissioner Variable', 'Commissioner', system-ui, sans-serif`

  // Ground and card.
  ctx.fillStyle = token('bg')
  ctx.fillRect(0, 0, WIDTH, HEIGHT)
  ctx.fillStyle = token('surface')
  roundRect(ctx, 40, 40, WIDTH - 80, HEIGHT - 80, 28)
  ctx.fill()
  ctx.fillStyle = token('you')
  ctx.fillRect(40 + 28, 40, WIDTH - 80 - 56, 6)

  const left = 88
  const right = WIDTH - 88

  ctx.fillStyle = token('text-muted')
  ctx.font = font(600, 22)
  ctx.fillText(
    `FOURTH & PROBABLE  ·  WEEK ${result.week}, ${result.season}  ·  ${formatScoringProfile(result.scoring_profile).toUpperCase()}`,
    left,
    104,
  )

  // The headline, worded exactly as the page words it.
  const a = result.team_a
  const b = result.team_b
  ctx.fillStyle = token('text-secondary')
  ctx.font = font(600, 26)
  ctx.fillText(`${labels.a} — estimated win probability`, left, 160)
  ctx.fillStyle = token('you')
  ctx.font = font(800, 120)
  ctx.fillText(formatPercent(a.win_probability), left - 4, 272)

  ctx.textAlign = 'right'
  ctx.fillStyle = token('text-secondary')
  ctx.font = font(600, 26)
  ctx.fillText(labels.b, right, 200)
  ctx.font = font(700, 64)
  ctx.fillText(formatPercent(b.win_probability), right, 272)
  ctx.textAlign = 'left'

  // The split bar.
  const barY = 300
  ctx.fillStyle = token('surface-sunken')
  roundRect(ctx, left, barY, right - left, 18, 9)
  ctx.fill()
  ctx.save()
  roundRect(ctx, left, barY, right - left, 18, 9)
  ctx.clip()
  ctx.fillStyle = token('you')
  ctx.fillRect(left, barY, (right - left) * a.win_probability, 18)
  ctx.restore()

  // Both ranges on one shared scale, as on the page.
  const low = Math.min(a.p10, b.p10)
  const high = Math.max(a.p90, b.p90)
  const pad = Math.max((high - low) * 0.08, 1)
  const scale = { min: low - pad, max: high + pad }
  drawRange(ctx, token, font, labels.a, a, 372, left, right, scale, true)
  drawRange(ctx, token, font, labels.b, b, 452, left, right, scale, false)

  ctx.fillStyle = token('text-muted')
  ctx.font = font(500, 21)
  ctx.fillText(
    `Share of ${result.simulation.iterations.toLocaleString()} simulated weeks. An estimate from each player's projected range, not a prediction.`,
    left,
    552,
  )

  return new Promise((resolve, reject) =>
    canvas.toBlob((blob) => (blob ? resolve(blob) : reject(new Error('Could not draw the card'))), 'image/png'),
  )
}

function drawRange(
  ctx: CanvasRenderingContext2D,
  token: (name: string) => string,
  font: (weight: number, size: number) => string,
  label: string,
  team: TeamSimulation,
  y: number,
  left: number,
  right: number,
  scale: { min: number; max: number },
  emphasis: boolean,
) {
  const x = (value: number) => left + ((value - scale.min) / (scale.max - scale.min)) * (right - left)

  ctx.fillStyle = token('text')
  ctx.font = font(700, 24)
  ctx.fillText(label, left, y)
  ctx.textAlign = 'right'
  ctx.fillStyle = token('text-muted')
  ctx.font = font(500, 20)
  ctx.fillText(
    `Low ${formatPoints(team.p10)} · Middle ${formatPoints(team.median_score)} · High ${formatPoints(team.p90)}`,
    right,
    y,
  )
  ctx.textAlign = 'left'

  const stripY = y + 14
  ctx.fillStyle = token('field')
  roundRect(ctx, left, stripY, right - left, 30, 8)
  ctx.fill()
  ctx.strokeStyle = token('range-whisker')
  ctx.lineWidth = 3
  ctx.beginPath()
  ctx.moveTo(x(team.p10), stripY + 15)
  ctx.lineTo(x(team.p90), stripY + 15)
  ctx.stroke()
  ctx.fillStyle = emphasis ? token('you') : token('range-box')
  roundRect(ctx, x(team.p25), stripY + 7, x(team.p75) - x(team.p25), 16, 4)
  ctx.fill()
  ctx.fillStyle = token('range-median')
  ctx.fillRect(x(team.median_score) - 2, stripY + 7, 4, 16)
}

function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  ctx.beginPath()
  ctx.roundRect(x, y, w, h, r)
}

/**
 * Hand the card to the system share sheet where there is one (a phone), and
 * download it everywhere else.
 */
export async function shareOrDownload(blob: Blob, filename: string, url: string): Promise<'shared' | 'downloaded'> {
  const file = new File([blob], filename, { type: 'image/png' })
  if (navigator.canShare?.({ files: [file] })) {
    try {
      await navigator.share({ files: [file], url })
      return 'shared'
    } catch (error) {
      // Dismissing the sheet is a choice, not a failure; anything else falls
      // through to a download so the button always produces the card.
      if (error instanceof DOMException && error.name === 'AbortError') return 'shared'
    }
  }
  const link = document.createElement('a')
  link.href = URL.createObjectURL(blob)
  link.download = filename
  link.click()
  setTimeout(() => URL.revokeObjectURL(link.href), 1000)
  return 'downloaded'
}
