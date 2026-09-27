import { Navigate, useSearchParams } from 'react-router-dom'

/**
 * `/players` — kept as a redirect into the one board.
 *
 * Players and Rankings were the same table behind two sets of controls:
 * position as a dropdown here, as tabs there; a team filter here and not
 * there. Readers had to learn which page had which filter. The board now lives
 * at `/rankings`, with position tabs and the team filter together, and this
 * route forwards every old link with its filters intact:
 * `/players?position=RB&team=KC&query=hall` → `/rankings/rb?team=KC&query=hall`.
 *
 * Player pages stay at `/players/:id`; only the list moved.
 */
export default function PlayersPage() {
  const [searchParams] = useSearchParams()
  const params = new URLSearchParams(searchParams)
  const position = params.get('position')
  params.delete('position')

  const path = position ? `/rankings/${encodeURIComponent(position.toLowerCase())}` : '/rankings'
  const search = params.toString()
  return <Navigate to={search ? `${path}?${search}` : path} replace />
}
