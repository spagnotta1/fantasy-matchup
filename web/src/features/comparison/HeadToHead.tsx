import { Scale } from 'lucide-react'

import { Badge, type BadgeTone } from '@/components/ui/Badge'
import { Card, CardBody, CardHeader } from '@/components/ui/Card'
import { ProvenanceBadge } from '@/components/domain/ProvenanceBadge'
import { formatPercent, formatPoints } from '@/utils/format'
import type { StartSit } from '@/api/schemas'

const VERDICTS: Record<string, { label: string; tone: BadgeTone; description: string }> = {
  clear: {
    label: 'Clear',
    tone: 'accent',
    description: 'One side wins comfortably more often than the other.',
  },
  lean: {
    label: 'Lean',
    tone: 'info',
    description: 'A real but modest edge — worth acting on, not worth agonising over.',
  },
  toss_up: {
    label: 'Toss-up',
    tone: 'neutral',
    description:
      'The edge is smaller than the week-to-week noise the model itself reports, so no recommendation is made.',
  },
}

/**
 * One head-to-head, as the API decided it.
 *
 * Everything here is served: the probability, the margin, the verdict, the
 * reasons and the caveats. Nothing is re-derived, and in particular a toss-up
 * is rendered as a toss-up. The API deliberately names nobody below a 58%
 * edge — inventing a pick there would be presenting a coin flip as advice, and
 * it is the single easiest way for a product like this to lose someone's trust.
 *
 * The rationale is the backend's own prose, shown as such. It is not model
 * reasoning and is not described as any.
 */
export function HeadToHeadCard({ result }: { result: StartSit }) {
  const nameA = result.a.projection.player.name
  const nameB = result.b.projection.player.name
  const verdict = VERDICTS[result.verdict] ?? {
    label: result.verdict,
    tone: 'neutral' as BadgeTone,
    description: '',
  }

  const recommendedName =
    result.recommended === result.a.projection.player.player_id
      ? nameA
      : result.recommended === result.b.projection.player.player_id
        ? nameB
        : null

  const probabilityA = result.win_probability
  const probabilityB = 1 - probabilityA

  return (
    <Card>
      <CardHeader
        as="h3"
        title={
          <span className="flex items-center gap-2">
            <Scale aria-hidden className="text-ink-muted size-4" />
            {nameA} vs {nameB}
          </span>
        }
        action={
          <div className="flex items-center gap-2">
            <Badge tone={verdict.tone}>{verdict.label}</Badge>
            <ProvenanceBadge provenance="derived" showLabel={false} />
          </div>
        }
      />

      <CardBody className="space-y-5">
        <div>
          <div className="text-ink mb-1.5 flex items-baseline justify-between gap-4 text-sm">
            <span className="truncate font-medium">
              {nameA} <span className="tnum text-ink-secondary">{formatPercent(probabilityA)}</span>
            </span>
            <span className="truncate text-right font-medium">
              <span className="tnum text-ink-secondary">{formatPercent(probabilityB)}</span> {nameB}
            </span>
          </div>

          {/* One hue at two strengths rather than two hues: the pair a reader
              must tell apart is exactly the pair a red/green split makes
              indistinguishable under the common colour deficiencies. The names
              and percentages above carry the identification either way. */}
          <div
            className="bg-surface-sunken flex h-3 overflow-hidden rounded-full"
            role="img"
            aria-label={`${nameA} outscores ${nameB} in ${formatPercent(probabilityA)} of simulated outcomes; ${nameB} outscores ${nameA} in ${formatPercent(probabilityB)}.`}
          >
            <div
              className="bg-chart-series transition-[width] duration-300"
              style={{ width: `${probabilityA * 100}%` }}
            />
            <div
              className="bg-chart-series/30 transition-[width] duration-300"
              style={{ width: `${probabilityB * 100}%` }}
            />
          </div>

          <p className="text-ink-muted mt-2 text-xs leading-relaxed">
            {recommendedName ? (
              <>
                <span className="text-ink-secondary font-medium">Start {recommendedName}.</span>{' '}
                {verdict.description} Expected margin {formatPoints(Math.abs(result.expected_margin))}{' '}
                points.
              </>
            ) : (
              <>
                <span className="text-ink-secondary font-medium">No recommendation.</span>{' '}
                {verdict.description} The expected margin is{' '}
                {formatPoints(Math.abs(result.expected_margin))} points, which is well inside both
                players&apos; ranges.
              </>
            )}
          </p>
        </div>

        {result.rationale.length > 0 && (
          <div>
            <h4 className="text-ink-muted mb-2 text-xs font-semibold tracking-wide uppercase">
              Why
            </h4>
            <ul className="text-ink-secondary space-y-1.5 text-sm">
              {result.rationale.map((line) => (
                <li key={line} className="flex gap-2 leading-relaxed">
                  <span aria-hidden className="text-ink-muted">
                    •
                  </span>
                  {line}
                </li>
              ))}
            </ul>
          </div>
        )}

        {result.caveats.length > 0 && (
          <div className="bg-caution-soft rounded-[var(--radius-control)] px-3 py-2.5">
            <h4 className="text-caution-text mb-1 text-xs font-semibold tracking-wide uppercase">
              Worth knowing
            </h4>
            <ul className="text-caution-text space-y-1 text-xs leading-relaxed">
              {result.caveats.map((caveat) => (
                <li key={caveat}>{caveat}</li>
              ))}
            </ul>
          </div>
        )}
      </CardBody>
    </Card>
  )
}
