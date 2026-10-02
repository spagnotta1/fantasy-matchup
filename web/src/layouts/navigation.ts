import {
  Activity,
  ArrowLeftRight,
  BarChart3,
  ClipboardList,
  FileText,
  GitCompareArrows,
  HeartPulse,
  LayoutDashboard,
  ListOrdered,
  Settings,
  Shield,
  Shuffle,
  Swords,
  Target,
  Radio,
  UserRound,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

export type NavGroup = 'week' | 'tools'

/** Somewhere a reader can go: what the sidebar, the phone bar and the palette all list. */
export interface Destination {
  to: string
  label: string
  icon: LucideIcon
  /** One line shown on hover in the sidebar and under the name in the palette. */
  description: string
}

export interface NavItem extends Destination {
  /** Whether the item appears in the compact mobile bar, which fits five. */
  primary: boolean
  group: NavGroup
  /**
   * Paths that are part of this destination without being under it. A team's
   * page lives at `/teams/BAL` and is reached from Matchups, so Matchups is
   * what is marked while it is open.
   */
  alsoAt?: string[]
}

export const NAV_GROUP_LABELS: Record<NavGroup, string> = {
  week: 'This week',
  tools: 'Tools',
}

/**
 * Primary navigation.
 *
 * Ordered by how often a manager needs it during a week, not alphabetically:
 * the dashboard answers "what changed?", rankings answer "who do I start?", and
 * simulation is the destination feature. Two groups: *this week* is the slate
 * and everything read off it, *tools* are the things a manager runs.
 *
 * It was thirteen entries. Four of them were the same slate from another
 * angle, and each had grown its own sidebar line: Teams is now a view of
 * Matchups (it is the same week's games, by team), and Injuries and Usage are
 * the two views of Reports. Track record and Settings are not about this week
 * at all and sit at the foot of the sidebar (`FOOT_ITEMS`). Nothing was
 * removed: every old address still works, and the command palette still lists
 * every page by its own name.
 *
 * Five items are `primary` — the mobile bar holds five and no more; a
 * thumb-reachable bar with more becomes a coin flip. Everything else is one tap
 * away in the header's menu, and one keystroke away in the command palette.
 */
export const NAV_ITEMS: NavItem[] = [
  {
    to: '/',
    label: 'Dashboard',
    icon: LayoutDashboard,
    description: 'What to pay attention to this week',
    primary: true,
    group: 'week',
  },
  {
    to: '/rankings',
    label: 'Rankings',
    icon: BarChart3,
    description: 'Every projected player, by position or team',
    primary: true,
    group: 'week',
  },
  {
    to: '/matchups',
    label: 'Matchups',
    icon: Swords,
    description: 'Games, defences, betting lines, upcoming schedule and every team',
    primary: true,
    group: 'week',
    alsoAt: ['/teams'],
  },
  {
    to: '/live',
    label: 'Live',
    icon: Radio,
    description: 'Games in progress and points so far (unofficial)',
    primary: false,
    group: 'week',
  },
  {
    to: '/reports',
    label: 'Reports',
    icon: FileText,
    description: "This week's injury report, and whose role is rising or falling",
    primary: false,
    group: 'week',
  },
  {
    to: '/my-team',
    label: 'My team',
    icon: UserRound,
    description: 'Your roster projected, and your best lineup',
    // In the five-slot mobile bar since Players merged into Rankings: the
    // roster is where most of a manager's week starts.
    primary: true,
    group: 'tools',
  },
  {
    to: '/simulation',
    label: 'Simulation',
    icon: Shuffle,
    description: 'Estimate your chances in a head-to-head matchup',
    primary: true,
    group: 'tools',
  },
  {
    to: '/compare',
    label: 'Compare',
    icon: GitCompareArrows,
    description: 'Compare players side by side for start/sit calls',
    primary: false,
    group: 'tools',
  },
  {
    to: '/trade',
    label: 'Trade analyzer',
    icon: ArrowLeftRight,
    description: 'Weigh a trade on rest-of-season value and see what it does to your lineup',
    primary: false,
    group: 'tools',
  },
]

/**
 * The foot of the sidebar: where the product accounts for itself and where it
 * is configured. Neither is part of a manager's week, so neither competes with
 * the list above for a place in it.
 */
export const FOOT_ITEMS: Destination[] = [
  {
    to: '/track-record',
    label: 'Track record',
    icon: Target,
    description: 'How past projections compared with what actually happened',
  },
  {
    to: '/settings',
    label: 'Settings',
    icon: Settings,
    description: 'Scoring, data sources and how the projections work',
  },
]

/**
 * Pages that have a name of their own without a sidebar line of their own.
 *
 * The first three are views of a sidebar entry, and someone who types "usage"
 * into the palette should land on the usage view, not on Reports. Mock Draft
 * was taken out of the sidebar on purpose (see the commit "Take Mock Draft out
 * of the navigation"), and the ADP value board belongs with it. The command
 * palette is the one place that lists every page.
 */
export const PALETTE_ONLY: Destination[] = [
  {
    to: '/reports/injuries',
    label: 'Injuries',
    icon: HeartPulse,
    description: "This week's injury report next to each projection",
  },
  {
    to: '/reports/usage',
    label: 'Usage trends',
    icon: Activity,
    description: 'Whose playing time and targets are rising or falling',
  },
  {
    to: '/matchups?view=teams',
    label: 'Teams',
    icon: Shield,
    description: "Each team's game, betting line and players",
  },
  {
    to: '/mock-draft',
    label: 'Mock draft',
    icon: ClipboardList,
    description: 'Practise a draft from any pick',
  },
  {
    to: '/draft-board',
    label: 'Draft board',
    icon: ListOrdered,
    description: 'Season-long value next to where players are being drafted',
  },
]

export function navGroups(): { group: NavGroup; label: string; items: NavItem[] }[] {
  return (Object.keys(NAV_GROUP_LABELS) as NavGroup[]).map((group) => ({
    group,
    label: NAV_GROUP_LABELS[group],
    items: NAV_ITEMS.filter((item) => item.group === group),
  }))
}

/**
 * Whether a destination is the one a path belongs to.
 *
 * A match on whole segments, so `/rankings/rb` is Rankings and
 * `/reportsomething` is not Reports. The dashboard is `/` and matches only
 * itself.
 */
export function isAt(item: Pick<NavItem, 'to' | 'alsoAt'>, pathname: string): boolean {
  const under = (base: string) => pathname === base || pathname.startsWith(`${base}/`)
  if (item.to === '/') return pathname === '/'
  return under(item.to) || (item.alsoAt ?? []).some(under)
}
