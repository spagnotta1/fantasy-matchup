import { Navigate, useLocation, useNavigate, useParams } from 'react-router-dom'

import { SegmentedControl } from '@/components/ui/SegmentedControl'

import InjuriesPage from './InjuriesPage'
import UsagePage from './UsagePage'

type Report = 'injuries' | 'usage'

const REPORTS: Report[] = ['injuries', 'usage']

/** What a report's filters are called in its address. Only its own are carried to it. */
const SLATE_PARAMS = ['season', 'week', 'scoring']

/**
 * Reports: the two lists a manager reads before setting a lineup.
 *
 * The injury report and the usage trends were two pages and two sidebar
 * entries. Both are this week's board read for one thing — who is hurt, whose
 * role is moving — and both are read in the same sitting, so they are two
 * views of one page, with the switch where Matchups has its own.
 *
 * The view is a path segment (`/reports/usage`), like a position on the board:
 * a link to the usage trends is a thing people send each other. Each view
 * keeps its own heading and its own question, because each still answers its
 * own. Switching carries the week and the scoring format across and leaves the
 * other view's filters behind: "Out & doubtful" means nothing to the usage
 * list.
 */
export default function ReportsPage() {
  const { report } = useParams<{ report: string }>()
  const { search } = useLocation()
  const navigate = useNavigate()

  // `/reports` is the injury report. An address that names no report this page
  // has goes there too, rather than drawing one under the wrong name.
  if (report === undefined || !REPORTS.includes(report as Report)) {
    return <Navigate to={{ pathname: '/reports/injuries', search }} replace />
  }
  const view = report as Report

  const switcher = (
    <SegmentedControl<Report>
      label="Report"
      value={view}
      onChange={(next) => {
        const current = new URLSearchParams(search)
        const kept = new URLSearchParams()
        for (const key of SLATE_PARAMS) {
          const value = current.get(key)
          if (value !== null) kept.set(key, value)
        }
        const query = kept.toString()
        navigate({ pathname: `/reports/${next}`, search: query ? `?${query}` : '' })
      }}
      options={[
        { value: 'injuries', label: 'Injuries' },
        { value: 'usage', label: 'Usage' },
      ]}
    />
  )

  return view === 'usage' ? <UsagePage action={switcher} /> : <InjuriesPage action={switcher} />
}
