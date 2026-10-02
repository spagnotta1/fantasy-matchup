import { Card, CardBody, CardHeader } from '@/components/ui/Card'
import { MatchupGradeChip } from '@/components/domain/MatchupGradeChip'
import { NotAppliedNotice, ProvenanceBadge } from '@/components/domain/ProvenanceBadge'
import { formatGameDay, formatPercent, formatPoints, formatSpread } from '@/utils/format'
import type { Matchup, PlayerContext, Usage } from '@/api/schemas'

/**
 * A list of label/value rows, in two columns where the card is wide enough.
 *
 * One column put a label at the card's left edge and its value at the right,
 * up to 1,100px apart on a desktop, with nothing but a hairline to carry the
 * eye across. Two columns halve that distance and the card's height. Sized by
 * the card (a query container), since a card is half the page at one width and
 * all of it at another.
 */
function Rows({ children }: { children: React.ReactNode }) {
  return <dl className="grid gap-x-8 @xl:grid-cols-2">{children}</dl>
}

/** A label/value row. Missing values render an em dash rather than disappearing. */
function Row({ label, value, hint }: { label: string; value: React.ReactNode; hint?: string }) {
  return (
    <div className="border-line flex items-baseline justify-between gap-4 border-b py-1.5">
      <dt className="text-ink-secondary text-sm">
        {label}
        {hint && <span className="text-ink-muted ml-1 text-detail">{hint}</span>}
      </dt>
      <dd className="tnum text-ink shrink-0 text-sm font-medium">{value}</dd>
    </div>
  )
}

/**
 * Opponent strength, computed above the model.
 *
 * The `applied_to_projection: false` notice is not boilerplate here — it is the
 * whole point. A matchup panel sitting beside a projection reads as "this is
 * why the number is what it is", and under the frozen model that is false. The
 * notice says so in the panel rather than in a footnote nobody reaches.
 */
export function MatchupPanel({
  matchup,
  opponent,
  isHome,
}: {
  matchup: Matchup | null | undefined
  opponent: string | null | undefined
  isHome: boolean | null | undefined
}) {
  return (
    <Card>
      <CardHeader
        as="h2"
        title="Matchup"
        description="How this week's opponent has defended the position over its last four games."
        action={<ProvenanceBadge provenance="derived" />}
      />
      <CardBody className="@container">
        {!matchup ? (
          <p className="text-ink-muted text-sm">
            No matchup this week — this player has no scheduled opponent.
          </p>
        ) : (
          <>
            <div className="mb-4 flex items-center gap-3">
              <MatchupGradeChip
                grade={matchup.grade}
                opponent={opponent}
                fpAllowed={matchup.fp_allowed_vs_position_l4}
                size="md"
              />
              <span className="text-ink text-sm font-medium">
                {isHome ? 'vs' : 'at'} {opponent ?? '—'}
              </span>
            </div>

            <Rows>
              <Row
                label="Defence rank vs this position"
                hint="1 = toughest"
                value={matchup.grade.defense_rank ?? '—'}
              />
              <Row
                label="Points allowed to this position"
                hint="per game, last 4"
                value={formatPoints(matchup.fp_allowed_vs_position_l4)}
              />
              <Row label="Targets allowed" hint="last 4" value={formatPoints(matchup.targets_allowed_l4)} />
              <Row label="Carries allowed" hint="last 4" value={formatPoints(matchup.carries_allowed_l4)} />
              <Row label="Overall defence rank" value={matchup.defense_rank_overall ?? '—'} />
              <Row label="Opponent pace" hint="their plays per game, last 4" value={formatPoints(matchup.opponent_pace_l4)} />
            </Rows>

            {!matchup.applied_to_projection && (
              <NotAppliedNotice reason="The projection does not adjust for the opponent. This is shown to help you judge the matchup yourself." />
            )}
          </>
        )}
      </CardBody>
    </Card>
  )
}

/** Trailing workload — the model's own inputs, restated for a reader. */
export function UsagePanel({ usage }: { usage: Usage }) {
  return (
    <Card>
      <CardHeader
        as="h2"
        title="Usage"
        description="How much this player has been used in past games. It describes recent weeks, not a prediction for this one."
        action={<ProvenanceBadge provenance="derived" />}
      />
      <CardBody className="@container">
        <Rows>
          <Row label="Snap share" hint="last 4" value={formatPercent(usage.snap_pct_l4, 1)} />
          <Row label="Snap share" hint="season" value={formatPercent(usage.snap_pct_season, 1)} />
          <Row label="Target share" hint="last 4" value={formatPercent(usage.target_share_l4, 1)} />
          <Row label="Targets" hint="per game, last 4" value={formatPoints(usage.targets_l4)} />
          <Row label="Carries" hint="per game, last 4" value={formatPoints(usage.carries_l4)} />
          <Row label="Opportunities" hint="per game, last 4" value={formatPoints(usage.opportunities_l4)} />
          <Row label="Fantasy points" hint="per game, last 4" value={formatPoints(usage.fp_l4)} />
          <Row label="Fantasy points" hint="per game, season" value={formatPoints(usage.fp_season)} />
          <Row
            label="Week-to-week swing"
            hint="points, last 4"
            value={formatPoints(usage.fp_volatility_l4)}
          />
          <Row label="Games played" hint="season" value={usage.games_played_season ?? '—'} />
        </Rows>
      </CardBody>
    </Card>
  )
}

/**
 * Weather, the betting market and the injury report.
 *
 * All three are observed and none is an input to the projection. Each block
 * carries its own not-applied notice with the reason the API supplied, because
 * the reasons differ and a single blanket disclaimer would flatten them.
 *
 * Side by side where the card has room for three: they are three separate
 * things to weigh, and stacked they were a screen of their own.
 */
export function ContextPanel({ context }: { context: PlayerContext }) {
  const { game, weather, injury } = context

  return (
    <Card>
      <CardHeader
        as="h2"
        title="Injury, weather and betting line"
        description="Useful for your own judgement. None of this is factored into the projection."
        action={<ProvenanceBadge provenance="context" />}
      />
      <CardBody className="@container">
        <div className="grid gap-6 @4xl:grid-cols-3">
          <section>
            <h3 className="text-ink-muted mb-2 text-caption font-semibold tracking-wide uppercase">
              Injury report
            </h3>
            {!injury ? (
              <p className="text-ink-muted text-sm">This player is not on the injury report this week.</p>
            ) : (
              <>
                <dl>
                  <Row label="Status" value={injury.report_status ?? 'Not listed'} />
                  <Row label="Practice" value={injury.practice_status ?? '—'} />
                  {injury.detail && <Row label="Detail" value={injury.detail} />}
                </dl>
                {injury.will_not_play && (
                  <p className="bg-negative-soft text-negative-text mt-3 rounded-[var(--radius-control)] px-3 py-2 text-detail leading-relaxed">
                    This player is ruled Out. The projection above assumes a normal game — we leave it
                    in place rather than showing zero, so you can tell &quot;not playing&quot; apart from
                    &quot;expected to score nothing&quot;.
                  </p>
                )}
                {!injury.applied_to_projection && (
                  <NotAppliedNotice reason={injury.unapplied_reason} />
                )}
              </>
            )}
          </section>

          <section>
            <h3 className="text-ink-muted mb-2 text-caption font-semibold tracking-wide uppercase">
              Weather
            </h3>
            {!weather ? (
              <p className="text-ink-muted text-sm">No forecast is available for this game.</p>
            ) : weather.is_indoor ? (
              <p className="text-ink-secondary text-sm">Indoor stadium — weather is not a factor.</p>
            ) : (
              <>
                <dl>
                  <Row label="Temperature" value={weather.temperature_f !== null && weather.temperature_f !== undefined ? `${Math.round(weather.temperature_f)}°F` : '—'} />
                  <Row label="Wind" value={weather.wind_mph !== null && weather.wind_mph !== undefined ? `${Math.round(weather.wind_mph)} mph` : '—'} />
                  <Row label="Chance of rain/snow" value={formatPercent(weather.precipitation_probability)} />
                  <Row label="Source" value={weather.source ?? '—'} />
                </dl>
                {weather.is_adverse && (
                  <p className="bg-caution-soft text-caution-text mt-3 rounded-[var(--radius-control)] px-3 py-2 text-detail leading-relaxed">
                    Bad-weather game: 20+ mph wind or a 60%+ chance of rain or snow.
                  </p>
                )}
                {!weather.applied_to_projection && <NotAppliedNotice reason={weather.unapplied_reason} />}
              </>
            )}
          </section>

          <section>
            <h3 className="text-ink-muted mb-2 text-caption font-semibold tracking-wide uppercase">
              Betting market
            </h3>
            {!game ? (
              <p className="text-ink-muted text-sm">No betting line is available for this game.</p>
            ) : (
              <>
                <dl>
                  <Row label="Kickoff" value={formatGameDay(game.gameday)} />
                  <Row label="Spread" value={formatSpread(game.team_spread)} />
                  <Row label="Over/under" value={formatPoints(game.total_line)} />
                  <Row label="Expected team points" value={formatPoints(game.implied_team_total)} />
                  <Row label="Rest" hint="days since last game" value={game.rest_days ?? '—'} />
                  {game.spread_source && <Row label="Line source" value={game.spread_source} />}
                </dl>
                {!game.applied_to_projection && <NotAppliedNotice reason={game.unapplied_reason} />}
              </>
            )}
          </section>
        </div>
      </CardBody>
    </Card>
  )
}
