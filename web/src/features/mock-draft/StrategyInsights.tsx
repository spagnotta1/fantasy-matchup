import { AlertTriangle, Clock, Layers, Scale } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

import { Card, CardBody, CardHeader } from '@/components/ui/Card'
import { ProvenanceBadge } from '@/components/domain/ProvenanceBadge'
import { formatNumber, formatPercent } from '@/utils/format'
import type { SeatAnalysis, StrategyInsight } from '@/api/schemas'

/**
 * What the simulations at this seat actually showed.
 *
 * Every card is a finding the backend measured and declined to emit when its
 * threshold was not met, so an empty list is a real answer — this seat has no
 * standing lean — rather than a rendering failure. The icon and the accent come
 * from `kind`, which is a stable code, so a new finding type on the server
 * renders with a sensible default here instead of breaking.
 */
const PRESENTATION: Record<string, { icon: LucideIcon; tone: string }> = {
  early_lean: { icon: Scale, tone: 'text-accent' },
  early_balanced: { icon: Scale, tone: 'text-ink-secondary' },
  tier_cliff: { icon: Layers, tone: 'text-caution-text' },
  deferrable: { icon: Clock, tone: 'text-positive-text' },
  urgent: { icon: AlertTriangle, tone: 'text-negative-text' },
}

export function StrategyInsights({ seat }: { seat: SeatAnalysis }) {
  if (seat.insights.length === 0) {
    return (
      <Card>
        <CardHeader title="Draft strategy" as="h2" />
        <CardBody>
          <p className="text-ink-secondary text-sm leading-relaxed">
            The simulations produced no finding that met its evidence threshold at this
            seat. That is a result rather than a gap: no position dominated the early
            rounds, no tier emptied sharply, and nothing was reliably deferrable.
          </p>
        </CardBody>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader
        title="Draft strategy"
        description={`Patterns measured across ${seat.simulations.toLocaleString()} simulated drafts from this seat.`}
        as="h2"
        action={<ProvenanceBadge provenance="derived" />}
      />
      <CardBody>
        <ul className="space-y-3">
          {seat.insights.map((insight, index) => (
            <InsightCard key={`${insight.kind}-${index}`} insight={insight} />
          ))}
        </ul>
      </CardBody>
    </Card>
  )
}

function InsightCard({ insight }: { insight: StrategyInsight }) {
  const presentation = PRESENTATION[insight.kind] ?? {
    icon: Scale,
    tone: 'text-ink-secondary',
  }
  const Icon = presentation.icon

  return (
    <li className="border-line rounded-[var(--radius-control)] border p-3">
      <div className="flex items-start gap-2.5">
        <Icon aria-hidden className={`mt-0.5 size-4 shrink-0 ${presentation.tone}`} />
        <div className="min-w-0 space-y-1">
          <h3 className="text-ink text-sm font-semibold">{insight.headline}</h3>
          <p className="text-ink-secondary text-sm leading-relaxed">{insight.detail}</p>
          <EvidenceList evidence={insight.evidence} />
        </div>
      </div>
    </li>
  )
}

/**
 * The numbers behind the sentence.
 *
 * Shown rather than trusted. Every finding is generated from these values, so
 * putting them beside the prose lets a reader check the claim instead of taking
 * it — which is the difference between an analysis and an assertion.
 */
function EvidenceList({ evidence }: { evidence: StrategyInsight['evidence'] }) {
  const entries = Object.entries(evidence).filter(
    (entry): entry is [string, string | number] => entry[1] != null,
  )
  if (entries.length === 0) return null

  return (
    <dl className="text-ink-muted flex flex-wrap gap-x-4 gap-y-1 pt-1 text-xs">
      {entries.map(([key, value]) => (
        <div key={key} className="flex gap-1.5">
          <dt>{humanise(key)}</dt>
          <dd className="text-ink-secondary tnum font-medium">{present(key, value)}</dd>
        </div>
      ))}
    </dl>
  )
}

function humanise(key: string): string {
  return key.replace(/_/g, ' ').replace(/^./, (character) => character.toUpperCase())
}

function present(key: string, value: string | number): string {
  if (typeof value === 'string') return value
  if (key.includes('share') || key.includes('probability')) return formatPercent(value)
  if (Number.isInteger(value)) return String(value)
  return formatNumber(value)
}
