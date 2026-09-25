import { useEffect, useRef, useState, type KeyboardEvent } from 'react'

import { formatPoints, formatSigned } from '@/utils/format'

export interface GameLogDatum {
  key: string
  label: string
  season: number
  week: number
  points: number
  opponent: string
  isHome: boolean
  projected: number | null
}

/** Plot insets: room for y ticks on the left and x labels underneath. */
const PAD = { top: 12, right: 8, bottom: 22, left: 30 }
const CHART_HEIGHT = 256
/** Columns are capped, per the chart spec: never fill the band. */
const MAX_BAR = 24
/** Roughly the widest x label ("'25 W17") at 11px, plus air. */
const LABEL_SLOT = 44

/** Round tick values spanning [min, max], about `count` of them. */
function niceTicks(min: number, max: number, count = 4): number[] {
  const span = Math.max(max - min, 1)
  const raw = span / count
  const magnitude = 10 ** Math.floor(Math.log10(raw))
  const step = [1, 2, 2.5, 5, 10].map((m) => m * magnitude).find((m) => m >= raw) ?? raw
  const ticks: number[] = []
  for (let value = Math.floor(min / step) * step; value < max + step; value += step) {
    ticks.push(Number(value.toFixed(6)))
    if (value >= max) break
  }
  return ticks
}

/** A column with a 4px rounded data end and a square baseline end. */
function columnPath(x: number, width: number, baseline: number, end: number): string {
  const r = Math.min(4, width / 2, Math.abs(baseline - end))
  // +1 rounds toward the baseline for a positive column, -1 for a negative one.
  const dir = end <= baseline ? 1 : -1
  return (
    `M${x},${baseline}V${end + dir * r}Q${x},${end} ${x + r},${end}` +
    `H${x + width - r}Q${x + width},${end} ${x + width},${end + dir * r}V${baseline}Z`
  )
}

function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null)
  const [width, setWidth] = useState(0)
  useEffect(() => {
    const node = ref.current
    if (!node) return
    const observer = new ResizeObserver(([entry]) => {
      if (entry) setWidth(Math.round(entry.contentRect.width))
    })
    observer.observe(node)
    return () => observer.disconnect()
  }, [])
  return [ref, width] as const
}

/**
 * The game-log column chart, drawn directly in SVG.
 *
 * It used to be Recharts — the app's only chart-library consumer — which cost a
 * 372 KB chunk (108 KB gzipped), parsed on every player page, to draw at most
 * seventeen columns and two lines. The marks, colours and thresholds are
 * unchanged. One thing is added: keyboard access. The plot is a single tab
 * stop and the arrow keys step the same readout the pointer shows, announced
 * through a live region. The table view remains the complete accessible form.
 */
export function GameLogChart({
  data,
  boomThreshold,
  bustThreshold,
}: {
  data: GameLogDatum[]
  boomThreshold: number | null
  bustThreshold: number | null
}) {
  const [containerRef, width] = useWidth<HTMLDivElement>()
  const [active, setActive] = useState<number | null>(null)

  if (data.length === 0) {
    return <p className="text-ink-muted text-sm">No scored games to chart.</p>
  }

  const values = data.map((datum) => datum.points)
  const thresholds = [boomThreshold, bustThreshold].filter((value): value is number => value !== null)
  // Fantasy points can go negative, so the baseline is zero and the domain
  // extends below it only when the data does.
  const ticks = niceTicks(Math.min(0, ...values), Math.max(1, ...values, ...thresholds))
  const low = ticks[0] ?? 0
  const high = ticks.at(-1) ?? 1

  const plotWidth = Math.max(width - PAD.left - PAD.right, 0)
  const plotHeight = CHART_HEIGHT - PAD.top - PAD.bottom
  const y = (value: number) => PAD.top + ((high - value) / (high - low)) * plotHeight
  const band = plotWidth / data.length
  // A 2px surface gap between adjacent columns when the band gets tight.
  const barWidth = Math.max(Math.min(MAX_BAR, band - 2), 1)
  const baseline = y(0)
  // Thin the x labels until they fit. The last (newest) always shows, and a
  // thinned label that would collide with it is dropped.
  const labelEvery = Math.max(1, Math.ceil(LABEL_SLOT / Math.max(band, 1)))
  const last = data.length - 1
  const showLabel = (index: number) =>
    index === last || (index % labelEvery === 0 && last - index >= labelEvery)

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const current = active ?? last
    const moves: Record<string, number | null> = {
      ArrowLeft: Math.max(0, current - 1),
      ArrowRight: Math.min(last, current + 1),
      Home: 0,
      End: last,
      Escape: null,
    }
    const next = moves[event.key]
    if (next === undefined) return
    event.preventDefault()
    setActive(next)
  }

  const activeDatum = active === null ? null : (data[active] ?? null)
  const anchor = active === null ? 0 : PAD.left + band * active + band / 2

  return (
    <div
      ref={containerRef}
      className="relative w-full rounded-sm"
      style={{ height: CHART_HEIGHT }}
      tabIndex={0}
      role="group"
      aria-label={`Fantasy points by game, ${data.length} games, oldest to newest. Use the arrow keys to read each game.`}
      onKeyDown={onKeyDown}
      onFocus={() => setActive((current) => current ?? last)}
      onBlur={() => setActive(null)}
      onPointerLeave={() => setActive(null)}
    >
      {width > 0 && (
        <svg width={width} height={CHART_HEIGHT} aria-hidden className="block">
          {ticks.map((tick) => (
            <g key={tick}>
              <line
                x1={PAD.left}
                x2={width - PAD.right}
                y1={y(tick)}
                y2={y(tick)}
                stroke={tick === 0 ? 'var(--color-chart-axis)' : 'var(--color-chart-grid)'}
                shapeRendering="crispEdges"
              />
              <text
                x={PAD.left - 6}
                y={y(tick)}
                textAnchor="end"
                dominantBaseline="middle"
                fill="var(--color-ink-muted)"
                fontSize={11}
                className="tnum"
              >
                {tick}
              </text>
            </g>
          ))}

          {data.map((datum, index) => {
            const x = PAD.left + band * index
            return (
              <g key={datum.key}>
                {active === index && (
                  <rect x={x} y={PAD.top} width={band} height={plotHeight} fill="var(--color-surface-hover)" />
                )}
                <path
                  data-chart-bar=""
                  d={columnPath(x + (band - barWidth) / 2, barWidth, baseline, y(datum.points))}
                  fill="var(--color-chart-series)"
                />
                {showLabel(index) && (
                  <text
                    x={x + band / 2}
                    y={CHART_HEIGHT - 6}
                    textAnchor="middle"
                    fill="var(--color-ink-muted)"
                    fontSize={11}
                  >
                    {datum.label}
                  </text>
                )}
                {/* The hit target is the whole band, not the painted column. */}
                <rect
                  x={x}
                  y={PAD.top}
                  width={band}
                  height={plotHeight}
                  fill="transparent"
                  onPointerEnter={() => setActive(index)}
                />
              </g>
            )
          })}

          {/* Thresholds the API supplied, so "boom" and "bust" mean the same
              thing here as they do in the probabilities above. */}
          {boomThreshold !== null && (
            <ThresholdLine
              y={y(boomThreshold)}
              x1={PAD.left}
              x2={width - PAD.right}
              label={`Boom ${formatPoints(boomThreshold)}`}
              above
            />
          )}
          {bustThreshold !== null && (
            <ThresholdLine
              y={y(bustThreshold)}
              x1={PAD.left}
              x2={width - PAD.right}
              label={`Bust ${formatPoints(bustThreshold)}`}
            />
          )}
          {/* No reference line for the player's average. It lands within a
              point of the boom threshold for most startable players, and two
              near-coincident horizontal rules read as one mislabelled line.
              The average is stated numerically directly beneath the chart. */}
        </svg>
      )}

      {activeDatum && (
        <div
          data-chart-tooltip=""
          className="bg-surface-raised border-line shadow-overlay pointer-events-none absolute top-0 z-10 rounded-[var(--radius-control)] border px-3 py-2 whitespace-nowrap"
          style={{
            left: anchor,
            // Beside the column, flipped left in the right half so the readout
            // never hangs off the card.
            transform: anchor > width / 2 ? 'translateX(calc(-100% - 12px))' : 'translateX(12px)',
          }}
        >
          <p className="text-ink text-xs font-semibold">
            {activeDatum.season} Week {activeDatum.week}
          </p>
          <p className="text-ink-muted text-xs">
            {activeDatum.isHome ? 'vs' : 'at'} {activeDatum.opponent}
          </p>
          <p className="text-ink tnum mt-1 text-sm font-medium">{formatPoints(activeDatum.points)} pts</p>
          {activeDatum.projected !== null && (
            <p className="text-ink-muted tnum text-xs">
              Projected {formatPoints(activeDatum.projected)} ·{' '}
              {formatSigned(activeDatum.points - activeDatum.projected)}
            </p>
          )}
        </div>
      )}

      <p className="sr-only" aria-live="polite">
        {activeDatum
          ? `${activeDatum.season} week ${activeDatum.week}, ${activeDatum.isHome ? 'versus' : 'at'} ${activeDatum.opponent}: ${formatPoints(activeDatum.points)} points` +
            (activeDatum.projected === null ? '' : `, projected ${formatPoints(activeDatum.projected)}`)
          : ''}
      </p>
    </div>
  )
}

function ThresholdLine({
  y,
  x1,
  x2,
  label,
  above = false,
}: {
  y: number
  x1: number
  x2: number
  label: string
  above?: boolean
}) {
  return (
    <g pointerEvents="none">
      <line x1={x1} x2={x2} y1={y} y2={y} stroke="var(--color-chart-reference)" strokeDasharray="4 4" />
      {/* The label sits over the newest columns, so it wears a surface-coloured
          halo: legible over a bar without moving off the line it names. */}
      <text
        x={x2 - 4}
        y={above ? y - 5 : y + 12}
        textAnchor="end"
        fill="var(--color-ink-secondary)"
        stroke="var(--color-surface)"
        strokeWidth={3}
        strokeLinejoin="round"
        paintOrder="stroke"
        fontSize={10}
      >
        {label}
      </text>
    </g>
  )
}
