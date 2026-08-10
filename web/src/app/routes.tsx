import { lazy } from 'react'
import { createBrowserRouter } from 'react-router-dom'

import { AppShell } from '@/layouts/AppShell'
import { RootErrorBoundary } from './RootErrorBoundary'

/**
 * Route-level code splitting.
 *
 * Every page is lazy except the shell. The dashboard is the common entry point,
 * but a user who lands on a player link should not download the simulation view
 * to see it — and the simulation view is the one that pulls in the charting
 * library.
 */
const DashboardPage = lazy(() => import('@/pages/DashboardPage'))
const PlayersPage = lazy(() => import('@/pages/PlayersPage'))
const PlayerDetailPage = lazy(() => import('@/pages/PlayerDetailPage'))
const RankingsPage = lazy(() => import('@/pages/RankingsPage'))
const MatchupsPage = lazy(() => import('@/pages/MatchupsPage'))
const ComparePage = lazy(() => import('@/pages/ComparePage'))
const SimulationPage = lazy(() => import('@/pages/SimulationPage'))
const MockDraftPage = lazy(() => import('@/pages/MockDraftPage'))
const SettingsPage = lazy(() => import('@/pages/SettingsPage'))
const NotFoundPage = lazy(() => import('@/pages/NotFoundPage'))

export const router = createBrowserRouter([
  {
    path: '/',
    element: <AppShell />,
    errorElement: <RootErrorBoundary />,
    children: [
      { index: true, element: <DashboardPage /> },
      { path: 'players', element: <PlayersPage /> },
      { path: 'players/:playerId', element: <PlayerDetailPage /> },
      { path: 'rankings', element: <RankingsPage /> },
      // The position is a route segment rather than a query param: a link to
      // the RB board is a thing people send each other.
      { path: 'rankings/:position', element: <RankingsPage /> },
      { path: 'matchups', element: <MatchupsPage /> },
      { path: 'matchups/:gameId', element: <MatchupsPage /> },
      { path: 'compare', element: <ComparePage /> },
      { path: 'simulation', element: <SimulationPage /> },
      { path: 'mock-draft', element: <MockDraftPage /> },
      { path: 'settings', element: <SettingsPage /> },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
])
