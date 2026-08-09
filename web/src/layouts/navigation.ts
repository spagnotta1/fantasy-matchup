import {
  BarChart3,
  GitCompareArrows,
  LayoutDashboard,
  Settings,
  Shuffle,
  Swords,
  Users,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

export interface NavItem {
  to: string
  label: string
  icon: LucideIcon
  /** One line shown in the desktop sidebar's expanded state and on hover. */
  description: string
  /** Whether the item appears in the compact mobile bar, which fits five. */
  primary: boolean
}

/**
 * Primary navigation.
 *
 * Ordered by how often a manager needs it during a week, not alphabetically:
 * the dashboard answers "what changed?", rankings answer "who do I start?", and
 * simulation is the destination feature. Settings is last and is not in the
 * mobile bar — five items is the most a thumb-reachable bar can hold without
 * the targets becoming a coin flip.
 */
export const NAV_ITEMS: NavItem[] = [
  {
    to: '/',
    label: 'Dashboard',
    icon: LayoutDashboard,
    description: 'What to pay attention to this week',
    primary: true,
  },
  {
    to: '/rankings',
    label: 'Rankings',
    icon: BarChart3,
    description: 'Weekly boards by position',
    primary: true,
  },
  {
    to: '/players',
    label: 'Players',
    icon: Users,
    description: 'Search, filter and browse projections',
    primary: true,
  },
  {
    to: '/matchups',
    label: 'Matchups',
    icon: Swords,
    description: 'Games, defensive form and context',
    primary: true,
  },
  {
    to: '/simulation',
    label: 'Simulation',
    icon: Shuffle,
    description: 'Simulate a head-to-head fantasy week',
    primary: true,
  },
  {
    to: '/compare',
    label: 'Compare',
    icon: GitCompareArrows,
    description: 'Side-by-side start/sit decisions',
    primary: false,
  },
  {
    to: '/settings',
    label: 'Settings',
    icon: Settings,
    description: 'Scoring, data sources and model detail',
    primary: false,
  },
]
