import { Navigate, useLocation } from 'react-router-dom'

/**
 * An address that moved, kept as a redirect to where it went.
 *
 * Links to the old address are in bookmarks, in messages people sent each
 * other, and in this product's own older pages, and every one of them carries
 * its filters in the query string. So the query goes along, with whatever the
 * new address needs added to it: `/usage?metric=target&position=WR` arrives at
 * `/reports/usage?metric=target&position=WR` showing the same rows.
 */
export default function MovedPage({ to, params }: { to: string; params?: Record<string, string> }) {
  const location = useLocation()
  const search = new URLSearchParams(location.search)
  for (const [key, value] of Object.entries(params ?? {})) search.set(key, value)
  const query = search.toString()
  return <Navigate to={{ pathname: to, search: query ? `?${query}` : '', hash: location.hash }} replace />
}
