import { Plus } from 'lucide-react'

import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { ProvenanceBadge } from '@/components/domain/ProvenanceBadge'
import { cn } from '@/utils/cn'
import { formatNumber, formatPercent, formatSigned } from '@/utils/format'
import type { TradeReplacement } from '@/api/schemas'

import { EVEN_SHARE, type EvenOut, type LineupResult, type TradeBalance } from './tradeMath'

const HEADLINES = {
  you: { text: 'Favours you', tone: 'text-positive-text' },
  them: { text: 'Favours them', tone: 'text-negative-text' },
  even: { text: 'Close to even', tone: 'text-ink' },
} as const

function summary(balance: TradeBalance): string {
  const gap = formatNumber(Math.abs(balance.gap), 0)
  const share = formatPercent(balance.share)
  if (balance.lean === 'you') return `You get ${gap} more in value than you give up (${share}).`
  if (balance.lean === 'them') return `You give up ${gap} more in value than you get (${share}).`
  return balance.gap === 0
    ? 'Both sides carry the same value.'
    : `The sides are ${gap} apart (${share}), inside the ${formatPercent(EVEN_SHARE)} this page calls even.`
}

/**
 * The balance strip: a centre line, the even band around it, and a fill that
 * runs toward whichever side the values lean. The band is drawn so the
 * threshold behind the headline is visible rather than asserted.
 */
function BalanceBar({ balance }: { balance: TradeBalance }) {
  const reach = Math.min(balance.share, 1) * 50
  const toYou = balance.gap >= 0
  const band = EVEN_SHARE * 50
  return (
    <div>
      <div
        className="bg-surface-sunken relative h-3.5 overflow-hidden rounded-full"
        role="img"
        aria-label={`${HEADLINES[balance.lean].text}: ${formatPercent(balance.share)} apart`}
      >
        <div
          aria-hidden
          className="bg-line absolute inset-y-0"
          style={{ left: `${50 - band}%`, width: `${band * 2}%` }}
        />
        <div
          aria-hidden
          className={cn(
            'absolute inset-y-0 transition-[left,width] duration-300 ease-out',
            balance.lean === 'even' ? 'bg-ink-muted' : toYou ? 'bg-positive' : 'bg-negative',
          )}
          style={{ left: `${toYou ? 50 : 50 - reach}%`, width: `${reach}%` }}
        />
        <div aria-hidden className="bg-ink absolute inset-y-0 left-1/2 w-0.5 -translate-x-1/2" />
      </div>
      <div className="text-ink-muted mt-1.5 flex justify-between text-[0.6875rem]">
        <span>Bad for you</span>
        <span>Even</span>
        <span>Good for you</span>
      </div>
    </div>
  )
}

function EvenOutLine({
  result,
  ownRoster,
  onAdd,
}: {
  result: EvenOut
  ownRoster: boolean
  onAdd: (side: 'give' | 'get', id: string) => void
}) {
  const range =
    result.rankLow === null
      ? null
      : result.rankLow === result.rankHigh
        ? `#${result.rankLow}`
        : `#${result.rankLow}–#${result.rankHigh}`
  const value = `${formatNumber(result.low, 0)}–${formatNumber(result.high, 0)}`

  if (result.candidates.length === 0) {
    return (
      <p className="text-ink-secondary text-sm leading-relaxed">
        No single player is worth the {value} it would take to even this out. It would take more than one.
      </p>
    )
  }

  const verb = result.side === 'give' ? 'add' : 'ask for'
  const source = result.side === 'give' ? (ownRoster ? 'from your team' : 'from your roster') : 'from them'
  return (
    <div className="space-y-2.5">
      <p className="text-ink-secondary text-sm leading-relaxed">
        To even it out, {verb} a player {source} worth {value}
        {range && (
          <>
            {' '}
            — ranked around <strong className="text-ink tnum">{range}</strong> overall
          </>
        )}
        .
      </p>
      <div className="flex flex-wrap gap-1.5">
        {result.candidates.map((candidate) => (
          <button
            key={candidate.player.player_id}
            type="button"
            onClick={() => onAdd(result.side, candidate.player.player_id)}
            className="border-line bg-surface hover:bg-surface-hover hover:border-line-strong text-ink inline-flex items-center gap-1.5 rounded-full border py-1 pr-2.5 pl-1.5 text-xs transition-colors"
          >
            <Plus aria-hidden className="text-ink-muted size-3.5" />
            <span className="font-medium">{candidate.player.name}</span>
            <span className="tnum text-ink-muted">
              #{candidate.overall_rank} · {formatNumber(candidate.trade_value, 0)}
            </span>
          </button>
        ))}
      </div>
    </div>
  )
}

function LineupImpact({
  before,
  after,
  notOnRoster,
  lean,
}: {
  before: LineupResult
  after: LineupResult
  notOnRoster: string[]
  lean: TradeBalance['lean']
}) {
  const change = after.total - before.total
  // Value adds up across a roster; a lineup does not. When the two disagree —
  // usually a two-for-one — the lineup is the one a manager plays, so say so.
  const disagrees = (lean === 'you' && change < -0.05) || (lean === 'them' && change > 0.05)
  const beforeIds = new Set(before.starters.map((v) => v.player.player_id))
  const afterIds = new Set(after.starters.map((v) => v.player.player_id))
  const joins = after.starters.filter((v) => !beforeIds.has(v.player.player_id))
  const leaves = before.starters.filter((v) => !afterIds.has(v.player.player_id))
  return (
    <div className="bg-surface-sunken rounded-[var(--radius-control)] px-4 py-3">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <p className="text-ink text-sm font-semibold">Your best lineup</p>
        <p className="tnum text-sm">
          <span className="text-ink-secondary">
            {formatNumber(before.total)} → {formatNumber(after.total)} pts/g
          </span>{' '}
          <span
            className={cn(
              'font-bold',
              change > 0.05 ? 'text-positive-text' : change < -0.05 ? 'text-negative-text' : 'text-ink',
            )}
          >
            {formatSigned(change)}
          </span>
        </p>
      </div>
      {disagrees && (
        <p className="text-ink mt-1.5 text-sm">
          {lean === 'you'
            ? 'You get more total value, but your starting lineup gets worse. The extra value sits on your bench.'
            : 'You give up more total value, but your starting lineup gets better.'}
        </p>
      )}
      <p className="text-ink-muted mt-1 text-xs leading-relaxed">
        {joins.length === 0 && leaves.length === 0
          ? 'Your starters do not change, so this trade moves only your bench.'
          : [
              joins.length ? `Starts: ${joins.map((v) => v.player.name).join(', ')}` : null,
              leaves.length ? `Leaves the lineup: ${leaves.map((v) => v.player.name).join(', ')}` : null,
            ]
              .filter(Boolean)
              .join('. ') + '.'}{' '}
        Each player&rsquo;s current per-game rate, on your roster from My team; bye weeks are not in it.
        {notOnRoster.length > 0 &&
          ` ${notOnRoster.join(', ')} ${notOnRoster.length === 1 ? 'is' : 'are'} not on that roster, so there is nothing to take out.`}
      </p>
    </div>
  )
}

/**
 * The verdict card: headline, balance strip, the way to even it out, and — for
 * a manager with a roster — what the trade does to their starting lineup.
 *
 * The headline is a statement about the sum of two columns of `derived`
 * values, and is worded as one. "Favours you" says which column is bigger; it
 * is not "you win", and the method is one click away, not a footnote away.
 */
export function TradeVerdict({
  balance,
  even,
  ownRoster,
  weekGap,
  weekMissing,
  lineup,
  notices,
  replacement,
  week,
  onAdd,
  onClear,
}: {
  balance: TradeBalance
  even: EvenOut | null
  ownRoster: boolean
  weekGap: number
  weekMissing: string[]
  lineup: { before: LineupResult; after: LineupResult; notOnRoster: string[] } | null
  notices: string[]
  replacement: TradeReplacement[]
  week: number | null
  onAdd: (side: 'give' | 'get', id: string) => void
  onClear: () => void
}) {
  const headline = HEADLINES[balance.lean]
  return (
    <Card className="mt-4 sm:mt-6">
      <div className="space-y-4 px-4 py-5 sm:px-6">
        <div>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-ink-muted text-xs font-medium">Estimated rest-of-season value</p>
            <ProvenanceBadge provenance="derived" />
          </div>
          <h2 className={cn('mt-1 text-3xl font-extrabold tracking-tight sm:text-4xl', headline.tone)}>
            {headline.text}
          </h2>
          <p className="text-ink-secondary mt-1 text-sm">{summary(balance)}</p>
        </div>

        <BalanceBar balance={balance} />

        <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          <div>
            <dt className="text-ink-muted text-xs">You give</dt>
            <dd className="tnum text-ink text-lg font-bold">{formatNumber(balance.give, 0)}</dd>
          </div>
          <div>
            <dt className="text-ink-muted text-xs">You get</dt>
            <dd className="tnum text-ink text-lg font-bold">{formatNumber(balance.get, 0)}</dd>
          </div>
          <div className="col-span-2 sm:col-span-1">
            <dt className="text-ink-muted text-xs">This week{week ? ` (week ${week})` : ''}</dt>
            <dd className="tnum text-ink text-lg font-bold">
              {formatSigned(weekGap)} <span className="text-ink-muted text-xs font-normal">projected pts</span>
            </dd>
            {weekMissing.length > 0 && (
              <dd className="text-caution-text text-[0.6875rem] leading-snug">
                {weekMissing.join(', ')} {weekMissing.length === 1 ? 'has' : 'have'} no projection this week
                (a bye or an inactive listing) and {weekMissing.length === 1 ? 'counts' : 'count'} as zero here.
              </dd>
            )}
          </div>
        </dl>

        {lineup && <LineupImpact {...lineup} lean={balance.lean} />}

        {even && (
          <div className="border-line border-t border-dashed pt-4">
            <EvenOutLine result={even} ownRoster={ownRoster} onAdd={onAdd} />
          </div>
        )}

        <div className="flex flex-wrap items-center gap-3">
          <Button size="sm" onClick={onClear}>
            Clear trade
          </Button>
        </div>

        <details className="group">
          <summary className="text-ink cursor-pointer text-sm font-semibold select-none">How the values work</summary>
          <div className="text-ink-secondary mt-3 space-y-3 text-xs leading-relaxed">
            <p>
              A player&rsquo;s value is the rest-of-season points they are projected to score above the best
              player at their position still on the waiver wire. Values add up across a trade: a throw-in below
              the waiver wire counts as zero, because you could pick up the same for free.
            </p>
            {replacement.length > 0 && (
              <p>
                Waiver-wire level this week:{' '}
                {replacement
                  .map((r) => `${r.position} ${r.name ?? '—'} (${formatNumber(r.value, 0)} pts)`)
                  .join(' · ')}
                .
              </p>
            )}
            <ul className="list-disc space-y-1.5 pl-4">
              {notices.map((notice) => (
                <li key={notice}>{notice}</li>
              ))}
              <li>
                &ldquo;Close to even&rdquo; means the sides are within {formatPercent(EVEN_SHARE)} of each other.
                That cutoff is a display choice, not a measured margin of error.
              </li>
            </ul>
          </div>
        </details>
      </div>
    </Card>
  )
}
