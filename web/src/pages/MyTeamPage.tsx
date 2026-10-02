import { Fragment, useState, type ReactNode } from 'react'
import { ArrowDownToLine, Copy, RotateCcw, Shuffle, Trash2, UserRound } from 'lucide-react'

import { Badge } from '@/components/ui/Badge'
import { Button, ButtonLink, IconButton } from '@/components/ui/Button'
import { Card, CardBody, CardHeader } from '@/components/ui/Card'
import {
  ColumnHeader,
  RowHeaderCell,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
} from '@/components/ui/DataTable'
import { PageHeader } from '@/components/ui/PageHeader'
import { Select } from '@/components/ui/Select'
import { SkeletonTable } from '@/components/ui/Skeleton'
import { EmptyState, ErrorState, NoticeList, Refreshing } from '@/components/feedback/States'
import { CompareBar } from '@/components/domain/CompareBar'
import { CompareTick } from '@/components/domain/CompareTick'
import { InjuryBadge } from '@/components/domain/InjuryBadge'
import { MatchupGradeChip } from '@/components/domain/MatchupGradeChip'
import { PlayerCell } from '@/components/domain/PlayerCell'
import { PlayerIdentity } from '@/components/domain/PlayerIdentity'
import { PlayerSearchField } from '@/components/domain/PlayerSearchField'
import { OutcomeRange, ProjectionValue } from '@/components/domain/ProjectionValue'
import { ProvenanceBadge } from '@/components/domain/ProvenanceBadge'
import { useSlate } from '@/app/slate-context'
import { useCompareSelection, type CompareSelection } from '@/hooks/useCompareSelection'
import { useMyLineup } from '@/hooks/useMyLineup'
import { boardCeiling } from '@/utils/board'
import { cn } from '@/utils/cn'
import { formatPoints } from '@/utils/format'
import type { RankedProjection } from '@/api/schemas'

const FANTASY_POSITIONS = ['QB', 'RB', 'WR', 'TE']

/**
 * My team: a roster, this week's projections for it, and the highest-projected
 * lineup it can field.
 *
 * The roster is a list in the URL (see `useRoster`) — no account, no saved
 * league. The lineup is the simulation builder's own autofill run over just
 * these players, in the board's projected order, and it says what it is: a
 * starting point filled slot by slot, not an optimiser.
 *
 * The manager can override it: bench a starter, or start a bench player in
 * any slot their position is eligible for. The choice lives in the link beside
 * the roster (`useLineupChoice`), and the page keeps saying how the chosen
 * lineup compares with the highest-projected one rather than hiding it.
 *
 * Two kinds of player are kept out of the lineup, and both are named rather
 * than dropped: anyone ruled out (the designation is a hard caveat; they keep
 * their projection, they just do not play) and anyone with no projection this
 * week (a bye, an inactive listing, or a run that does not cover them).
 *
 * Every lineup and bench row opens with a tick box, and a bar at the foot of
 * the screen goes to the comparison of whoever is ticked: the starter and the
 * bench player a manager is choosing between are on this page, two tables
 * apart. The ticks are in the link (`?compare=`) beside the roster.
 */
export default function MyTeamPage() {
  const slate = useSlate()
  const {
    ids,
    setIds,
    setChoice,
    board,
    catalog,
    byId,
    projected,
    ruledOut,
    unprojected,
    lineup,
    bench,
    customised,
    total,
    bestTotal,
    openSlots,
    fits,
    simulateHref,
    writeLineup,
  } = useMyLineup()
  const compare = useCompareSelection()
  const [copied, setCopied] = useState(false)

  const benchSlot = (index: number) =>
    writeLineup(lineup.map((row, i) => (i === index ? null : row.player)))
  const startInSlot = (index: number, playerId: string) => {
    const player = byId.get(playerId)?.projection.player ?? null
    writeLineup(
      lineup.map((row, i) => {
        if (i === index) return player
        // A starter moved into another slot leaves their old one empty.
        return row.player?.player_id === playerId ? null : row.player
      }),
    )
  }
  const slotOptions = (entry: RankedProjection) =>
    lineup.flatMap((row, index) =>
      fits(entry, row.slot)
        ? [
            {
              value: String(index),
              label: row.player ? `${row.slot} — replace ${row.player.name}` : `${row.slot} — empty slot`,
            },
          ]
        : [],
    )
  const benchOptions = (slot: string) =>
    bench
      .filter((entry) => fits(entry, slot))
      .map((entry) => ({ value: entry.projection.player.player_id, label: entry.projection.player.name }))
  const scaleMax = boardCeiling(projected)

  const copyLink = async () => {
    try {
      await navigator.clipboard.writeText(window.location.href)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 2000)
    } catch {
      setCopied(false)
    }
  }

  return (
    <>
      <PageHeader
        title="My team"
        question={`Who should I start from my roster in week ${slate.week ?? '—'}?`}
        action={
          ids.length > 0 && (
            <div className="flex gap-2">
              <Button size="sm" variant="secondary" onClick={() => void copyLink()}>
                <Copy aria-hidden className="size-3.5" />
                {copied ? 'Link copied' : 'Copy link'}
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  setIds([])
                  setChoice(null)
                }}
              >
                <Trash2 aria-hidden className="size-3.5" />
                Clear
              </Button>
            </div>
          )
        }
      />

      <NoticeList
        className="mb-4"
        notices={[
          'Your roster lives in this page’s link and in this browser — there is no account and nothing is stored on a server. Copy the link to keep it or open it elsewhere.',
        ]}
      />

      <Card className="mb-6">
        <CardBody>
          <PlayerSearchField
            label="Add a player"
            placeholder="Search QB, RB, WR or TE…"
            positions={FANTASY_POSITIONS}
            excludeIds={ids}
            onSelect={(player) => setIds([...ids, player.player_id])}
          />
        </CardBody>
      </Card>

      {ids.length === 0 ? (
        <Card>
          <EmptyState
            titleAs="h2"
            icon={<UserRound aria-hidden className="size-5" />}
            eyebrow="On the sideline"
            title="Add your roster"
            description="Search for your players above. We will show their projections, fill in your highest-projected lineup and flag anyone ruled out."
          />
        </Card>
      ) : board.isPending || catalog.isPending ? (
        <Card>
          <SkeletonTable rows={8} columns={5} />
        </Card>
      ) : board.isError ? (
        <Card>
          <ErrorState error={board.error} onRetry={() => void board.refetch()} />
        </Card>
      ) : (
        <Refreshing active={board.isPlaceholderData}>
          {(ruledOut.length > 0 || unprojected.length > 0) && (
            <Card className="mb-6">
              <CardHeader as="h2" title="Not in the lineup" description="Kept out of the lineup below, with the reason." />
              <ul className="divide-line divide-y">
                {ruledOut.map((entry) => (
                  <li key={entry.projection.player.player_id} className="flex items-center gap-3 px-4 py-2.5">
                    <PlayerIdentity player={entry.projection.player} team={entry.projection.team} size="sm" className="flex-1" />
                    <InjuryBadge injury={entry.projection.context.injury} />
                    <span className="text-right">
                      <ProjectionValue points={entry.projection.prediction.points} />
                      <span className="text-negative-text block text-chip font-medium">Ruled out — will not play</span>
                    </span>
                  </li>
                ))}
                {unprojected.map((r) => (
                  <li key={r.id} className="flex items-center gap-3 px-4 py-2.5">
                    {r.player ? (
                      <PlayerIdentity player={r.player} size="sm" className="flex-1" />
                    ) : (
                      <span className="text-ink-secondary flex-1 text-sm">{r.id}</span>
                    )}
                    <span className="text-ink-muted text-detail">No projection this week — usually a bye week or an inactive listing</span>
                    <Button
                      variant="link"
                      size="sm"
                      className="text-ink-muted underline"
                      onClick={() => setIds(ids.filter((id) => id !== r.id))}
                    >
                      Remove
                    </Button>
                  </li>
                ))}
              </ul>
            </Card>
          )}

          <Card className="mb-6 overflow-clip">
            <CardHeader
              as="h2"
              title={
                customised
                  ? `Your lineup — ${formatPoints(total)} pts`
                  : `Highest-projected lineup — ${formatPoints(total)} pts`
              }
              description={
                customised
                  ? `${catalog.format.label}. You have changed this lineup. It projects ${formatPoints(Math.abs(bestTotal - total))} pts ${total <= bestTotal ? 'below' : 'above'} the highest-projected lineup (${formatPoints(bestTotal)} pts).`
                  : `${catalog.format.label}. Filled with your highest-projected players, slot by slot — a starting point, not the final word. Use Bench and Start to change it.`
              }
              action={
                <div className="flex flex-wrap items-center gap-2">
                  <ProvenanceBadge provenance="model" />
                  {customised && (
                    <Button size="sm" variant="ghost" onClick={() => setChoice(null)}>
                      <RotateCcw aria-hidden className="size-3.5" />
                      Reset
                    </Button>
                  )}
                  {lineup.some((r) => r.player) && (
                    // The page's next step, so it looks like one: this is where
                    // "who do I start" becomes "do I win", with the lineup
                    // already filled in.
                    <ButtonLink to={simulateHref} variant="primary" size="sm" icon={<Shuffle aria-hidden />}>
                      Estimate my chance of winning
                    </ButtonLink>
                  )}
                </div>
              }
            />
            <RosterTable
              caption="Starting lineup with this week's projections"
              rows={lineup.map((row, index) => {
                const entry = row.player ? byId.get(row.player.player_id) : undefined
                const fillers = entry ? [] : benchOptions(row.slot)
                return {
                  slot: row.slot,
                  entry,
                  emptyNote:
                    fillers.length > 0
                      ? 'Empty — choose a bench player to start here'
                      : 'Empty — no eligible player on your bench',
                  move: entry
                    ? () => (
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => benchSlot(index)}
                          aria-label={`Move ${entry.projection.player.name} to the bench`}
                        >
                          <ArrowDownToLine aria-hidden className="size-3.5" />
                          Bench
                        </Button>
                      )
                    : fillers.length > 0
                      ? (size) => (
                          <MoveSelect
                            label={`Start a player at ${row.slot}`}
                            placeholder="Start…"
                            options={fillers}
                            size={size}
                            onChoose={(playerId) => startInSlot(index, playerId)}
                          />
                        )
                      : undefined,
                }
              })}
              scaleMax={scaleMax}
              compare={compare}
              onRemove={(id) => setIds(ids.filter((x) => x !== id))}
            />
            {openSlots > 0 && (
              <CardBody className="border-line text-caution-text border-t py-3 text-detail">
                {openSlots} {openSlots === 1 ? 'slot is' : 'slots are'} empty. An empty slot scores zero.
              </CardBody>
            )}
          </Card>

          {bench.length > 0 && (
            <Card className="overflow-clip">
              <CardHeader
                as="h2"
                title="Bench"
                description={
                  customised
                    ? 'Not in your starting lineup. Use Start to move a player into a slot.'
                    : 'Projected lower than the starter in their slot. Use Start to move a player in anyway.'
                }
              />
              <RosterTable
                caption="Bench players with this week's projections"
                rows={bench.map((entry) => {
                  const options = slotOptions(entry)
                  return {
                    slot: 'BN',
                    entry,
                    move: (size) =>
                      options.length > 0 ? (
                        <MoveSelect
                          label={`Start ${entry.projection.player.name}`}
                          placeholder="Start in…"
                          options={options}
                          size={size}
                          onChoose={(value) => startInSlot(Number(value), entry.projection.player.player_id)}
                        />
                      ) : (
                        <span className="text-ink-muted text-detail">No eligible slot</span>
                      ),
                  }
                })}
                scaleMax={scaleMax}
                compare={compare}
                onRemove={(id) => setIds(ids.filter((x) => x !== id))}
              />
            </Card>
          )}
        </Refreshing>
      )}

      {/* Outside `Refreshing`, which makes what it wraps inert while a week
          loads: the bar is the way out of a selection, and stays usable. */}
      <CompareBar selection={compare} />
    </>
  )
}

/**
 * The control that moves a row between the lineup and the bench.
 *
 * A function of size because it is drawn in two places: in its own column
 * where the table has room for one, and on the row's second line where it does
 * not — a phone — where a 32px menu is too small a target for a thumb.
 */
type MoveControl = (size: 'sm' | 'md') => ReactNode

function RosterTable({
  caption,
  rows,
  scaleMax,
  compare,
  onRemove,
}: {
  caption: string
  rows: { slot: string; entry: RankedProjection | undefined; move?: MoveControl; emptyNote?: string }[]
  scaleMax: number
  compare: CompareSelection
  onRemove: (playerId: string) => void
}) {
  // A finished week prints "actual 18.4" beside each projection, which needs
  // the room a bare number does not.
  const hasActuals = rows.some((row) => row.entry?.projection.actual_points != null)

  return (
    // The shared table, laid out by the room the table itself has (a query
    // container), not by the window: the sidebar takes 240px of a laptop, and
    // at 1,024px that squeezed the name into 60px and cut "Start in…" off at
    // the card's edge.
    //
    //   under 42rem   Slot, Player, Projection, and each player's matchup and
    //                 actions on a second line. Seven columns do not fit a
    //                 phone, and scrolling sideways hid "Start in…" — the only
    //                 way to promote a bench player.
    //   from 42rem    one line: the matchup and the actions get columns.
    //   from 60rem    the range strip gets one too.
    //
    // The layout is fixed, so the table can never be wider than its card: the
    // player column takes what is left and the name wraps inside it.
    //
    // The tick box is a column at every width. It is how two of these rows
    // reach the comparison, and a phone is where a start/sit call is made.
    // Under a finger it is 44px, most of which the slot column gives up: a
    // slot badge needs 48px and had 72, and the name beside it needs every
    // pixel a 360px phone has.
    <Table className="@container" caption={caption} layout="fixed">
      <TableHead>
        <ColumnHeader className="w-9 pointer-coarse:w-11">
          <span className="sr-only">Compare</span>
        </ColumnHeader>
        <ColumnHeader className="w-12 px-0">Slot</ColumnHeader>
        <ColumnHeader>Player</ColumnHeader>
        <ColumnHeader className="hidden w-26 @2xl:table-cell">Matchup</ColumnHeader>
        <ColumnHeader className="hidden w-52 @[60rem]:table-cell">Range</ColumnHeader>
        <ColumnHeader
          numeric
          aria-label="Projection"
          // On the two-line layout a bare projection needs 64px, and the
          // 16px it does not use is what the tick box cost the name.
          className={hasActuals ? 'w-20 @2xl:w-40' : 'w-16 @2xl:w-26'}
        >
          <span className="@2xl:hidden">Proj.</span>
          <span className="@max-2xl:hidden">Projection</span>
        </ColumnHeader>
        <ColumnHeader className="hidden w-38 @2xl:table-cell">
          <span className="sr-only">Move</span>
        </ColumnHeader>
        <ColumnHeader className="hidden w-16 @2xl:table-cell">
          <span className="sr-only">Remove</span>
        </ColumnHeader>
      </TableHead>
      <TableBody>
        {rows.map(({ slot, entry, move, emptyNote }, index) => {
          const last = index === rows.length - 1
          return (
            <Fragment key={entry?.projection.player.player_id ?? `${slot}-${index}`}>
              <TableRow
                className={cn(
                  // On the two-line layout the rule is under the second line.
                  entry && '@max-2xl:[&>*]:border-b-0',
                  // The second line is still the last row in the document when
                  // it is not drawn, so the table's own "no rule under the last
                  // row" does not reach this one.
                  last && entry && '@2xl:[&>*]:border-b-0',
                )}
              >
                <TableCell className="relative p-0">
                  {entry && (
                    <CompareTick
                      name={entry.projection.player.name}
                      ticked={compare.has(entry.projection.player.player_id)}
                      full={compare.full}
                      onToggle={() => compare.toggle(entry.projection.player.player_id)}
                      // The whole cell: 44px across under a finger. Laid
                      // over it, so it adds nothing to the row's height.
                      className="absolute inset-0"
                    />
                  )}
                </TableCell>
                <TableCell className="px-0">
                  {/* Squared: a slot is a mark in a column, not a status. */}
                  <Badge tone={slot === 'BN' ? 'neutral' : 'accent'} className="rounded-chip">
                    {slot}
                  </Badge>
                </TableCell>
                {entry ? (
                  <>
                    <RowHeaderCell>
                      {/* Not the row's link. A row here holds Bench, Start and
                          Remove, and a press that just misses one of them must
                          not leave the page. */}
                      <PlayerCell
                        player={entry.projection.player}
                        rowLink={false}
                        meta={
                          <>
                            {entry.projection.player.position} · {entry.projection.team}{' '}
                            {entry.projection.is_home ? 'vs' : '@'} {entry.projection.opponent}
                          </>
                        }
                      >
                        <InjuryBadge injury={entry.projection.context.injury} />
                      </PlayerCell>
                    </RowHeaderCell>
                    <TableCell className="hidden @2xl:table-cell">
                      <span data-matchup className="inline-flex">
                        <MatchupGradeChip
                          grade={entry.projection.matchup?.grade}
                          opponent={entry.projection.opponent}
                          fpAllowed={entry.projection.matchup?.fp_allowed_vs_position_l4}
                        />
                      </span>
                    </TableCell>
                    <TableCell className="hidden @[60rem]:table-cell">
                      <OutcomeRange
                        floor={entry.projection.prediction.points.floor}
                        p25={entry.projection.prediction.points.p25}
                        median={entry.projection.prediction.points.median}
                        p75={entry.projection.prediction.points.p75}
                        ceiling={entry.projection.prediction.points.ceiling}
                        threshold={entry.projection.prediction.points.boom_threshold}
                        scaleMax={scaleMax}
                      />
                    </TableCell>
                    <TableCell numeric>
                      <ProjectionValue
                        points={entry.projection.prediction.points}
                        actualPoints={entry.projection.actual_points}
                        // Stacked on the two-line layout: "20.5 actual 31.1" on
                        // one line is wider than the column.
                        className="@max-2xl:flex-col @max-2xl:items-end @max-2xl:gap-0"
                      />
                    </TableCell>
                    <TableCell className="hidden text-right @2xl:table-cell">{move?.('sm')}</TableCell>
                    <TableCell className="hidden text-right @2xl:table-cell">
                      <RemoveButton
                        name={entry.projection.player.name}
                        onRemove={() => onRemove(entry.projection.player.player_id)}
                      />
                    </TableCell>
                  </>
                ) : (
                  <>
                    {/* Two columns at either width: the player and the
                        projection on the two-line layout, the player and the
                        matchup on the wide one. */}
                    <TableCell colSpan={2} className="text-ink-muted text-detail">
                      {emptyNote ?? 'Empty — no eligible player on this roster'}
                      {move && <div className="mt-2 mb-1 @2xl:hidden">{move('md')}</div>}
                    </TableCell>
                    <TableCell className="hidden @[60rem]:table-cell" />
                    <TableCell className="hidden @2xl:table-cell" />
                    <TableCell className="hidden text-right @2xl:table-cell">{move?.('sm')}</TableCell>
                    <TableCell className="hidden @2xl:table-cell" />
                  </>
                )}
              </TableRow>
              {entry && (
                // The second line of the two-line layout: the matchup and the
                // row's two actions under the player, full width.
                <TableRow className="@2xl:hidden">
                  <TableCell colSpan={4} className="pt-0 pb-2.5">
                    <div className="flex items-center justify-between gap-3">
                      <span data-matchup className="inline-flex">
                        <MatchupGradeChip
                          grade={entry.projection.matchup?.grade}
                          opponent={entry.projection.opponent}
                          fpAllowed={entry.projection.matchup?.fp_allowed_vs_position_l4}
                        />
                      </span>
                      <span className="flex items-center gap-2">
                        {move?.('md')}
                        <RemoveButton
                          name={entry.projection.player.name}
                          onRemove={() => onRemove(entry.projection.player.player_id)}
                        />
                      </span>
                    </div>
                  </TableCell>
                </TableRow>
              )}
            </Fragment>
          )
        })}
      </TableBody>
    </Table>
  )
}

/**
 * Takes a player off the roster.
 *
 * It sits beside Bench and Start, so it is as large as they are: 32px with a
 * mouse and 44px under a finger. At 22px it was the smallest control on the
 * page and the one whose mis-tap costs the most.
 */
function RemoveButton({ name, onRemove }: { name: string; onRemove: () => void }) {
  return (
    <IconButton label={`Remove ${name}`} onClick={onRemove}>
      <Trash2 />
    </IconButton>
  )
}

/**
 * A one-shot "move here" menu: choosing an option acts immediately and the
 * menu returns to its placeholder. A native select, so it works by keyboard and
 * on a phone without a custom popover.
 */
function MoveSelect({
  label,
  placeholder,
  options,
  size = 'sm',
  onChoose,
}: {
  label: string
  placeholder: string
  options: { value: string; label: string }[]
  size?: 'sm' | 'md'
  onChoose: (value: string) => void
}) {
  return (
    <Select
      label={label}
      hideLabel
      size={size}
      value=""
      className="ml-auto w-32"
      options={[{ value: '', label: placeholder, disabled: true }, ...options]}
      onChange={(event) => {
        if (event.target.value) onChoose(event.target.value)
      }}
    />
  )
}
