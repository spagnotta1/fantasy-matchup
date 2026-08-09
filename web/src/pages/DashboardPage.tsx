import { PageHeader } from '@/components/ui/PageHeader'
import { NoticeList, Refreshing } from '@/components/feedback/States'
import { CalibrationNotice } from '@/components/domain/CalibrationNotice'
import { BestMatchups } from '@/features/dashboard/BestMatchups'
import { RiskOpportunity } from '@/features/dashboard/RiskOpportunity'
import { SimulationCallout } from '@/features/dashboard/SimulationCallout'
import { TopProjections } from '@/features/dashboard/TopProjections'
import { WeekOverview } from '@/features/dashboard/WeekOverview'
import { useBoard } from '@/hooks/useProjections'
import { useSlate } from '@/app/slate-context'

/**
 * The home screen.
 *
 * Ordered by the question a manager asks first: is there a board, who is
 * projected highest, who has the softest draw, and what is unusual. Every panel
 * reads the same cached board request — one network call feeds three of them,
 * which is the reason they are separate components rather than one giant one.
 *
 * Deliberately absent: a "biggest movers" panel. Movement is the difference
 * between two published runs, and the API exposes one run per week with no
 * history endpoint for projection changes. Showing week-over-week deltas would
 * mean comparing different players' weeks and calling it movement.
 */
export default function DashboardPage() {
  const slate = useSlate()
  const { data, isPlaceholderData } = useBoard()

  return (
    <>
      <PageHeader
        title={slate.week === null ? 'This week' : `Week ${slate.week}`}
        // "Week 14" alone is a fine heading under a sidebar that says which
        // product it belongs to, and a useless browser tab.
        documentTitle={slate.week === null ? 'Dashboard' : `Week ${slate.week} dashboard`}
        question="What should I pay attention to before lineups lock?"
      />

      <div className="mb-6 space-y-3">
        <CalibrationNotice projections={data?.data.map((entry) => entry.projection)} />
        {data && <NoticeList notices={data.meta.notices} />}
      </div>

      {/*
        `min-w-0` on both columns is load-bearing, not decoration. A grid item
        defaults to `min-width: auto`, so it refuses to shrink below its
        widest descendant's min-content — one long unbreakable row was pushing
        the whole dashboard 58px past a 390px viewport.
      */}
      {/*
        One veil over all four panels rather than four. They read the same
        cached board, so on a week change they go stale together — dimming them
        individually would stagger four separate fades across the screen for
        what is a single event.
      */}
      <Refreshing active={isPlaceholderData} label={`Loading week ${slate.week ?? ''}`.trim()}>
        <div className="grid gap-6 xl:grid-cols-2">
          <div className="min-w-0 space-y-6">
            <WeekOverview />
            <BestMatchups />
          </div>
          <div className="min-w-0 space-y-6">
            <TopProjections />
            <RiskOpportunity />
            {/*
              Last, deliberately. The dashboard answers "what should I care
              about this week?" first; the simulation is what a manager does
              *with* that answer, so it reads as the next step rather than
              competing with the boards above it.
            */}
            <SimulationCallout />
          </div>
        </div>
      </Refreshing>
    </>
  )
}
