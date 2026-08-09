import { Card, CardBody, CardHeader } from '@/components/ui/Card'
import { MatchupGradeChip } from '@/components/domain/MatchupGradeChip'
import { NotAppliedNotice, ProvenanceBadge } from '@/components/domain/ProvenanceBadge'
import { formatGameDay, formatPercent, formatPoints, formatSpread } from '@/utils/format'
import type { Matchup, PlayerContext, Usage } from '@/api/schemas'

/** A label/value row. Missing values render an em dash rather than disappearing. */
function Row({ label, value, hint }: { label: string; value: React.ReactNode; hint?: string }) {
  return (
    <div className="border-line flex items-baseline justify-between gap-4 border-b py-1.5 last:border-b-0">
      <dt className="text-ink-secondary text-sm">
        {label}
        {hint && <span className="text-ink-muted ml-1 text-xs">{hint}</span>}
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
        description="Trailing four completed games of defensive form, ranked within position."
        action={<ProvenanceBadge provenance="derived" />}
      />
      <CardBody>
        {!matchup ? (
          <p className="text-ink-muted text-sm">
            No matchup data is available — this player has no scheduled opponent for the week.
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

            <dl>
              <Row
                label="Defence rank vs position"
                hint="1 = toughest"
                value={matchup.grade.defense_rank ?? '—'}
              />
              <Row
                label="Points allowed to position"
                hint="per game, last 4"
                value={formatPoints(matchup.fp_allowed_vs_position_l4)}
              />
              <Row label="Targets allowed" hint="last 4" value={formatPoints(matchup.targets_allowed_l4)} />
              <Row label="Carries allowed" hint="last 4" value={formatPoints(matchup.carries_allowed_l4)} />
              <Row label="Overall defence rank" value={matchup.defense_rank_overall ?? '—'} />
              <Row label="Opponent pace" hint="plays/game, last 4" value={formatPoints(matchup.opponent_pace_l4)} />
            </dl>

            {!matchup.applied_to_projection && (
              <NotAppliedNotice reason="The frozen model does not consume a matchup feature. This is analysis presented beside the projection, not an adjustment to it." />
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
        description="Every window ends at the previous week — this is not a forecast of Sunday's snap count."
        action={<ProvenanceBadge provenance="derived" />}
      />
      <CardBody>
        <dl>
          <Row label="Snap share" hint="last 4" value={formatPercent(usage.snap_pct_l4, 1)} />
          <Row label="Snap share" hint="season" value={formatPercent(usage.snap_pct_season, 1)} />
          <Row label="Target share" hint="last 4" value={formatPercent(usage.target_share_l4, 1)} />
          <Row label="Targets" hint="per game, last 4" value={formatPoints(usage.targets_l4)} />
          <Row label="Carries" hint="per game, last 4" value={formatPoints(usage.carries_l4)} />
          <Row label="Opportunities" hint="per game, last 4" value={formatPoints(usage.opportunities_l4)} />
          <Row label="Fantasy points" hint="per game, last 4" value={formatPoints(usage.fp_l4)} />
          <Row label="Fantasy points" hint="per game, season" value={formatPoints(usage.fp_season)} />
          <Row
            label="Volatility"
            hint="std dev, last 4"
            value={formatPoints(usage.fp_volatility_l4)}
          />
          <Row label="Games played" hint="season" value={usage.games_played_season ?? '—'} />
        </dl>
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
 */
export function ContextPanel({ context }: { context: PlayerContext }) {
  const { game, weather, injury } = context

  return (
    <Card>
      <CardHeader
        as="h2"
        title="Context"
        description="Observed facts the model does not consume. Useful for your judgement; not folded into the number."
        action={<ProvenanceBadge provenance="context" />}
      />
      <CardBody className="space-y-6">
        <section>
          <h3 className="text-ink-muted mb-2 text-xs font-semibold tracking-wide uppercase">
            Injury report
          </h3>
          {!injury ? (
            <p className="text-ink-muted text-sm">No injury designation is on file for this week.</p>
          ) : (
            <>
              <dl>
                <Row label="Status" value={injury.report_status ?? 'Not listed'} />
                <Row label="Practice" value={injury.practice_status ?? '—'} />
                {injury.detail && <Row label="Detail" value={injury.detail} />}
              </dl>
              {injury.will_not_play && (
                <p className="bg-negative-soft text-negative-text mt-3 rounded-[var(--radius-control)] px-3 py-2 text-xs leading-relaxed">
                  This player is designated Out. The projection above still describes a full
                  workload — it is not zeroed, because &quot;projected zero&quot; and &quot;not
                  playing&quot; are different statements.
                </p>
              )}
              {!injury.applied_to_projection && (
                <NotAppliedNotice reason={injury.unapplied_reason} />
              )}
            </>
          )}
        </section>

        <section>
          <h3 className="text-ink-muted mb-2 text-xs font-semibold tracking-wide uppercase">
            Weather
          </h3>
          {!weather ? (
            <p className="text-ink-muted text-sm">No forecast is available for this game.</p>
          ) : weather.is_indoor ? (
            <p className="text-ink-secondary text-sm">Indoor venue — conditions are not a factor.</p>
          ) : (
            <>
              <dl>
                <Row label="Temperature" value={weather.temperature_f !== null && weather.temperature_f !== undefined ? `${Math.round(weather.temperature_f)}°F` : '—'} />
                <Row label="Wind" value={weather.wind_mph !== null && weather.wind_mph !== undefined ? `${Math.round(weather.wind_mph)} mph` : '—'} />
                <Row label="Precipitation" value={formatPercent(weather.precipitation_probability)} />
                <Row label="Source" value={weather.source ?? '—'} />
              </dl>
              {weather.is_adverse && (
                <p className="bg-caution-soft text-caution-text mt-3 rounded-[var(--radius-control)] px-3 py-2 text-xs leading-relaxed">
                  Flagged as adverse: 20+ mph wind or 60%+ chance of precipitation, outdoors.
                </p>
              )}
              {!weather.applied_to_projection && <NotAppliedNotice reason={weather.unapplied_reason} />}
            </>
          )}
        </section>

        <section>
          <h3 className="text-ink-muted mb-2 text-xs font-semibold tracking-wide uppercase">
            Betting market
          </h3>
          {!game ? (
            <p className="text-ink-muted text-sm">No market data is available for this game.</p>
          ) : (
            <>
              <dl>
                <Row label="Kickoff" value={formatGameDay(game.gameday)} />
                <Row label="Spread" value={formatSpread(game.team_spread)} />
                <Row label="Game total" value={formatPoints(game.total_line)} />
                <Row label="Implied team total" value={formatPoints(game.implied_team_total)} />
                <Row label="Rest" hint="days" value={game.rest_days ?? '—'} />
                {game.spread_source && <Row label="Line source" value={game.spread_source} />}
              </dl>
              {!game.applied_to_projection && <NotAppliedNotice reason={game.unapplied_reason} />}
            </>
          )}
        </section>
      </CardBody>
    </Card>
  )
}
