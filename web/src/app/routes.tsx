import { lazy } from 'react'
import { createBrowserRouter } from 'react-router-dom'

import { AppShell } from '@/layouts/AppShell'
import { RootErrorBoundary } from './RootErrorBoundary'

/**
 * Route-level code splitting.
 *
 * Every page is lazy except the shell. The dashboard is the common entry point,
 * but a user who lands on a player link should not download the simulation or
 * mock-draft views — the two largest page chunks — to see it.
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
const TeamsPage = lazy(() => import('@/pages/TeamsPage'))
const InjuriesPage = lazy(() => import('@/pages/InjuriesPage'))
const UsagePage = lazy(() => import('@/pages/UsagePage'))
const TrackRecordPage = lazy(() => import('@/pages/TrackRecordPage'))
const DraftBoardPage = lazy(() => import('@/pages/DraftBoardPage'))
const LivePage = lazy(() => import('@/pages/LivePage'))
const MyTeamPage = lazy(() => import('@/pages/MyTeamPage'))
const TradePage = lazy(() => import('@/pages/TradePage'))
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
      // The position is a route segment rather than a query param: a link to
      // the RB board is a thing people send each other. It is *optional* —
      // one route, not two — so moving between position tabs is a param
      // change on a mounted page rather than a new route. The shell keys its
      // Suspense boundary on the route, and two routes here meant every tab
      // click tore down and rebuilt the whole board.
      { path: 'rankings/:position?', element: <RankingsPage /> },
      { path: 'matchups/:gameId?', element: <MatchupsPage /> },
      { path: 'compare', element: <ComparePage /> },
      { path: 'simulation', element: <SimulationPage /> },
      { path: 'mock-draft', element: <MockDraftPage /> },
      // Optional segment, one route: moving between teams is a param change on
      // a mounted page, not a remount (see the rankings note above).
      { path: 'teams/:team?', element: <TeamsPage /> },
      { path: 'injuries', element: <InjuriesPage /> },
      { path: 'usage', element: <UsagePage /> },
      { path: 'track-record', element: <TrackRecordPage /> },
      { path: 'draft-board', element: <DraftBoardPage /> },
      { path: 'live', element: <LivePage /> },
      { path: 'my-team', element: <MyTeamPage /> },
      { path: 'trade', element: <TradePage /> },
      { path: 'settings', element: <SettingsPage /> },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
])
