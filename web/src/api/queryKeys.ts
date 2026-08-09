/**
 * Every cache key in the application, in one place.
 *
 * Centralised so that invalidation is possible at all: a key spelled inline in
 * a component is a key nothing else can target. The hierarchy is
 * `[domain, resource, params]`, which lets `['projections']` invalidate every
 * board without knowing what filters are in flight.
 */

import type { BoardParams, SlateParams } from './projections'
import type { PlayerListParams } from './players'
import type { SimulationRequest } from './schemas'

export const queryKeys = {
  /** Capability data: rarely changes, cached hard. */
  catalog: {
    all: ['catalog'] as const,
    health: () => [...queryKeys.catalog.all, 'health'] as const,
    seasons: () => [...queryKeys.catalog.all, 'seasons'] as const,
    weeks: (season: number) => [...queryKeys.catalog.all, 'weeks', season] as const,
    scoringProfiles: () => [...queryKeys.catalog.all, 'scoring-profiles'] as const,
    positions: () => [...queryKeys.catalog.all, 'positions'] as const,
    lineupSlots: () => [...queryKeys.catalog.all, 'lineup-slots'] as const,
    provenance: () => [...queryKeys.catalog.all, 'provenance'] as const,
    teams: () => [...queryKeys.catalog.all, 'teams'] as const,
    model: () => [...queryKeys.catalog.all, 'model'] as const,
  },

  projections: {
    all: ['projections'] as const,
    board: (params: BoardParams) => [...queryKeys.projections.all, 'board', params] as const,
    rankings: (position: string, params: SlateParams & { limit?: number }) =>
      [...queryKeys.projections.all, 'rankings', position, params] as const,
    player: (playerId: string, params: SlateParams) =>
      [...queryKeys.projections.all, 'player', playerId, params] as const,
  },

  players: {
    all: ['players'] as const,
    list: (params: PlayerListParams) => [...queryKeys.players.all, 'list', params] as const,
    search: (query: string) => [...queryKeys.players.all, 'search', query] as const,
    detail: (playerId: string) => [...queryKeys.players.all, 'detail', playerId] as const,
    profile: (playerId: string, params: SlateParams & { weeks?: number }) =>
      [...queryKeys.players.all, 'profile', playerId, params] as const,
    history: (playerId: string, params: { scoringProfile?: string | null; weeks?: number }) =>
      [...queryKeys.players.all, 'history', playerId, params] as const,
  },

  matchups: {
    all: ['matchups'] as const,
    games: (season: number | null | undefined, week: number | null | undefined) =>
      [...queryKeys.matchups.all, 'games', season ?? null, week ?? null] as const,
    week: (week: number, season: number | null | undefined) =>
      [...queryKeys.matchups.all, 'week', week, season ?? null] as const,
    game: (gameId: string, params: SlateParams) =>
      [...queryKeys.matchups.all, 'game', gameId, params] as const,
    defense: (params: SlateParams & { position?: string | null }) =>
      [...queryKeys.matchups.all, 'defense', params] as const,
    teamOutlook: (team: string, params: SlateParams) =>
      [...queryKeys.matchups.all, 'team-outlook', team, params] as const,
  },

  advice: {
    all: ['advice'] as const,
    startSit: (a: string, b: string, params: SlateParams) =>
      [...queryKeys.advice.all, 'start-sit', a, b, params] as const,
    compare: (playerIds: string[], params: SlateParams) =>
      [...queryKeys.advice.all, 'compare', [...playerIds].sort(), params] as const,
  },

  simulations: {
    all: ['simulations'] as const,
    run: (request: SimulationRequest) => [...queryKeys.simulations.all, 'run', request] as const,
  },
} as const
