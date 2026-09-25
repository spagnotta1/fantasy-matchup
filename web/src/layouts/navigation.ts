import {
  Activity,
  ArrowLeftRight,
  BarChart3,
  ClipboardList,
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
  Users,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

export type NavGroup = 'week' | 'tools' | 'model'

export interface NavItem {
  to: string
  label: string
  icon: LucideIcon
  /** One line shown in the desktop sidebar's expanded state and on hover. */
  description: string
  /** Whether the item appears in the compact mobile bar, which fits five. */
  primary: boolean
  group: NavGroup
}

export const NAV_GROUP_LABELS: Record<NavGroup, string> = {
  week: 'This week',
  tools: 'Tools',
  model: 'Behind the numbers',
}

/**
 * Primary navigation.
 *
 * Ordered by how often a manager needs it during a week, not alphabetically:
 * the dashboard answers "what changed?", rankings answer "who do I start?", and
 * simulation is the destination feature. Grouped because the list outgrew a
 * single column a reader can scan: *this week* is the slate and everything
 * read off it, *tools* are the things a manager runs, and *the model* is where
 * the product accounts for itself.
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
    description: "This week's rankings by position",
    primary: true,
    group: 'week',
  },
  {
    to: '/players',
    label: 'Players',
    icon: Users,
    description: 'Search and filter every projected player',
    primary: true,
    group: 'week',
  },
  {
    to: '/matchups',
    label: 'Matchups',
    icon: Swords,
    description: 'Games, defences, betting lines and upcoming schedule',
    primary: true,
    group: 'week',
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
    to: '/teams',
    label: 'Teams',
    icon: Shield,
    description: "Each team's game, betting line and players",
    primary: false,
    group: 'week',
  },
  {
    to: '/injuries',
    label: 'Injuries',
    icon: HeartPulse,
    description: "This week's injury report next to each projection",
    primary: false,
    group: 'week',
  },
  {
    to: '/usage',
    label: 'Usage trends',
    icon: Activity,
    description: 'Whose playing time and targets are rising or falling',
    primary: false,
    group: 'week',
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
    to: '/my-team',
    label: 'My team',
    icon: UserRound,
    description: 'Your roster projected, and your best lineup',
    primary: false,
    group: 'tools',
  },
  {
    to: '/trade',
    label: 'Trade helper',
    icon: ArrowLeftRight,
    description: 'See what each side gives and gets in a trade',
    primary: false,
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
    to: '/track-record',
    label: 'Track record',
    icon: Target,
    description: 'How past projections compared with what actually happened',
    primary: false,
    group: 'model',
  },
  {
    to: '/settings',
    label: 'Settings',
    icon: Settings,
    description: 'Scoring, data sources and how the projections work',
    primary: false,
    group: 'model',
  },
]

/**
 * Destinations that exist but are deliberately not in the navigation.
 *
 * Mock Draft was taken out of the sidebar on purpose (see the commit "Take Mock
 * Draft out of the navigation"), and the ADP value board belongs with it. Both
 * stay reachable by link and from the command palette, which is the one place
 * that lists every page.
 */
export const HIDDEN_DESTINATIONS: Omit<NavItem, 'primary' | 'group'>[] = [
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
