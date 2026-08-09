import { Suspense } from 'react'
import { Outlet, ScrollRestoration, useLocation } from 'react-router-dom'

import { RouteChrome } from '@/app/RouteChrome'
import { SlateProvider } from '@/app/SlateProvider'
import { SkeletonCards, SkeletonTable } from '@/components/ui/Skeleton'

import { MobileNav, Sidebar } from './Sidebar'
import { TopBar } from './TopBar'

/**
 * The persistent application shell.
 *
 * Everything outside `<Outlet />` survives navigation: the sidebar, the header
 * and the slate selection. Only the content region swaps, which is what makes
 * changing views feel instant rather than like loading a new page.
 */
export function AppShell() {
  const location = useLocation()

  return (
    // The slate selection lives inside the router because it is held in the
    // URL — a link to "week 18, PPR" has to be a link.
    <SlateProvider>
      <div className="bg-bg flex min-h-dvh">
        {/*
          Top of the page on a new navigation, and back where you were on a
          back/forward one. Router keys the saved offsets by history entry,
          which is the part that cannot be done with a `scrollTo(0, 0)`.
        */}
        <ScrollRestoration />
        <RouteChrome />

        <a href="#main" className="skip-link bg-accent text-on-accent rounded-md px-3 py-2 text-sm font-medium">
          Skip to content
        </a>

        <Sidebar />

        <div className="flex min-w-0 flex-1 flex-col">
          <TopBar />

          <main
            id="main"
            tabIndex={-1}
            // The bottom padding clears the fixed mobile bar. Without it the
            // last row of every list is permanently behind the navigation.
            className="mx-auto w-full max-w-[1600px] flex-1 px-4 pt-6 pb-24 sm:px-6 lg:pb-10"
          >
            {/*
              Keyed by pathname so a route change remounts the boundary.
              Without it, navigating from a loaded page to a lazy one shows the
              previous page's content frozen while the chunk downloads.
            */}
            <Suspense key={location.pathname} fallback={<RouteFallback pathname={location.pathname} />}>
              <Outlet />
            </Suspense>
          </main>
        </div>

        <MobileNav />
      </div>
    </SlateProvider>
  )
}

/**
 * The chunk-download placeholder.
 *
 * Shaped like the page that is arriving rather than one generic grid. A board
 * that resolves into a table after a card grid was drawn moves every row on the
 * screen; matching the destination's shape is the difference between a page
 * that fades in and a page that rearranges itself under the reader.
 *
 * The route is the only thing knowable here — the page's own component has not
 * downloaded yet — so the mapping is by path, and anything unrecognised falls
 * back to cards.
 */
function RouteFallback({ pathname }: { pathname: string }) {
  const isBoard = pathname.startsWith('/rankings') || pathname === '/players'

  return (
    <div className="animate-fade-in space-y-6">
      <div className="space-y-2">
        <div className="bg-surface-sunken animate-shimmer h-7 w-48 rounded-md" />
        <div className="bg-surface-sunken animate-shimmer h-4 w-72 rounded-md" />
      </div>
      {isBoard ? (
        <div className="bg-surface border-line rounded-[var(--radius-card)] border">
          <SkeletonTable rows={10} columns={6} />
        </div>
      ) : (
        <SkeletonCards count={6} />
      )}
    </div>
  )
}
