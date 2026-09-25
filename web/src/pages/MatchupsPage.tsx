import { useParams, useSearchParams } from 'react-router-dom'

import { PageHeader } from '@/components/ui/PageHeader'
import { SegmentedControl } from '@/components/ui/SegmentedControl'
import { DefenseBoard } from '@/features/matchups/DefenseBoard'
import { GameAnalysis } from '@/features/matchups/GameAnalysis'
import { GameList } from '@/features/matchups/GameList'
import { LinesBoard } from '@/features/matchups/LinesBoard'
import { ScheduleGrid } from '@/features/matchups/ScheduleGrid'
import { useSlate } from '@/app/slate-context'

type MatchupView = 'games' | 'defense' | 'lines' | 'schedule'

const VIEWS: MatchupView[] = ['games', 'defense', 'lines', 'schedule']

/**
 * Matchups, at two zoom levels.
 *
 * *Games* is the slate: pick a game, get both defences broken out by position
 * and the players who face them. *Defence* is the league-wide board for one
 * position, which is the view you want when you already know you need a tight
 * end and are looking for the softest one available.
 *
 * *Lines* is the betting market's read on each game, shown because the model
 * does not use it; *Schedule* is every team's run of remaining opponents at one
 * position, graded on current form.
 *
 * The tab lives in the query string and the game in the path, so both are
 * linkable and the back button walks the way a user expects.
 */
export default function MatchupsPage() {
  const { gameId } = useParams<{ gameId: string }>()
  const [searchParams, setSearchParams] = useSearchParams()
  const slate = useSlate()

  const requested = searchParams.get('view') as MatchupView | null
  const view: MatchupView = requested && VIEWS.includes(requested) ? requested : 'games'

  const setView = (next: MatchupView) => {
    setSearchParams(
      (current) => {
        const params = new URLSearchParams(current)
        if (next === 'games') params.delete('view')
        else params.set('view', next)
        return params
      },
      { replace: true },
    )
  }

  // A game is open: it is its own screen, not a tab within this one.
  if (gameId) return <GameAnalysis gameId={gameId} />

  return (
    <>
      <PageHeader
        title="Matchups"
        question="Which defences can I attack this week, and who benefits?"
        action={
          <SegmentedControl<MatchupView>
            label="Matchup view"
            value={view}
            onChange={setView}
            options={[
              { value: 'games', label: 'Games' },
              { value: 'defense', label: 'Defence' },
              { value: 'lines', label: 'Lines' },
              { value: 'schedule', label: 'Schedule' },
            ]}
          />
        }
      />

      {view === 'games' ? (
        <>
          <p className="text-ink-muted mb-4 text-xs">
            {slate.week === null
              ? 'Select a week to see its schedule.'
              : `Week ${slate.week} schedule. Open a game to see how each defence matches up by position.`}
          </p>
          <GameList />
        </>
      ) : view === 'defense' ? (
        <DefenseBoard />
      ) : view === 'lines' ? (
        <LinesBoard />
      ) : (
        <ScheduleGrid />
      )}
    </>
  )
}
