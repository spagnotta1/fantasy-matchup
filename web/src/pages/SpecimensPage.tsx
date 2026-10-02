import { useState, type ReactNode } from 'react'
import { ArrowRight, Copy, Play, Search, Settings, Trash2, UserPlus, X } from 'lucide-react'

import { Badge } from '@/components/ui/Badge'
import { Button, ButtonLink, IconButton, IconButtonLink, type ButtonSize, type ButtonVariant } from '@/components/ui/Button'
import { Card, CardBody, CardHeader } from '@/components/ui/Card'
import {
  ColumnHeader,
  DataTable,
  GroupHeaderRow,
  RowHeaderCell,
  RowLink,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  type DataTableColumn,
  type TableDensity,
} from '@/components/ui/DataTable'
import { FilterChip, FilterChoice, FilterSearch, FilterToolbar } from '@/components/ui/FilterToolbar'
import { PageHeader } from '@/components/ui/PageHeader'
import { SegmentedControl } from '@/components/ui/SegmentedControl'
import { EmptyState } from '@/components/feedback/States'
import { useUrlState } from '@/hooks/useUrlState'
import { formatPercent, formatPoints } from '@/utils/format'
import { parseSort } from '@/utils/tableSort'

/**
 * Every primitive, in every state, on one page.
 *
 * Not linked from the navigation and not in the search palette: this is a
 * workbench, reached by typing `/specimens`. It is the real components drawn
 * with the real tokens, so a change to either shows up here first, and the
 * screenshot tests photograph it in both themes at both widths.
 *
 * The rows below are written into this file. They are sample data, shaped like
 * a board, and are not projections.
 */

interface SampleRow {
  id: string
  name: string
  team: string
  opponent: string
  grade: string
  note: string
  floor: number
  ceiling: number
  boom: number | null
  points: number | null
  tier: number
}

const ROWS: SampleRow[] = [
  { id: 'r01', name: 'Jahmyr Gibbs', team: 'DET', opponent: '@ CAR', grade: 'A+', note: 'Full workload', floor: 9.7, ceiling: 32.5, boom: 0.41, points: 19.4, tier: 1 },
  { id: 'r02', name: 'Kenneth Walker III', team: 'KC', opponent: '@ LV', grade: 'D+', note: 'Limited in practice on Wednesday and Thursday, full on Friday', floor: 8.1, ceiling: 30.9, boom: 0.34, points: 17.9, tier: 2 },
  { id: 'r03', name: 'Derrick Henry', team: 'BAL', opponent: 'vs TEN', grade: 'B-', note: 'Full workload', floor: 7.3, ceiling: 30.2, boom: 0.3, points: 17.1, tier: 2 },
  { id: 'r04', name: 'Bijan Robinson', team: 'ATL', opponent: '@ NO', grade: 'A-', note: 'Full workload', floor: 6.7, ceiling: 29.5, boom: 0.28, points: 16.5, tier: 2 },
  { id: 'r05', name: 'Jonathan Taylor', team: 'IND', opponent: '@ WAS', grade: 'F', note: 'Questionable', floor: 4.6, ceiling: 27.5, boom: 0.22, points: 14.4, tier: 3 },
  { id: 'r06', name: "D'Andre Swift", team: 'CHI', opponent: 'vs NYJ', grade: 'B+', note: 'Full workload', floor: 4.0, ceiling: 26.8, boom: 0.2, points: 13.8, tier: 3 },
  { id: 'r07', name: 'Breece Hall', team: 'NYJ', opponent: '@ CHI', grade: 'C+', note: 'Full workload', floor: 4.0, ceiling: 26.8, boom: 0.2, points: 13.8, tier: 3 },
  { id: 'r08', name: 'Kyren Williams', team: 'LA', opponent: '@ PHI', grade: 'C-', note: 'Full workload', floor: 3.9, ceiling: 26.7, boom: 0.2, points: 13.7, tier: 3 },
  { id: 'r09', name: 'Christian McCaffrey', team: 'SF', opponent: 'vs SEA', grade: 'B', note: 'Out', floor: 3.5, ceiling: 26.1, boom: 0.18, points: 13.2, tier: 3 },
  { id: 'r10', name: 'Saquon Barkley', team: 'PHI', opponent: 'vs LA', grade: 'C', note: 'Full workload', floor: 3.1, ceiling: 25.6, boom: 0.17, points: 12.8, tier: 3 },
  { id: 'r11', name: 'Josh Jacobs', team: 'GB', opponent: '@ MIN', grade: 'B-', note: 'Full workload', floor: 2.8, ceiling: 25.0, boom: 0.16, points: 12.3, tier: 3 },
  { id: 'r12', name: 'A rookie with no history', team: 'TEN', opponent: '@ BAL', grade: '—', note: 'No trailing window, so no projection', floor: 0, ceiling: 0, boom: null, points: null, tier: 3 },
]

/** Enough rows to scroll the header out of view, which is what proves it stays. */
const LONG_ROWS: SampleRow[] = [0, 1, 2].flatMap((lap) =>
  ROWS.map((row) => ({
    ...row,
    id: `${row.id}-${lap}`,
    points: row.points === null ? null : row.points - lap * 1.3,
  })),
)

const COLUMNS: DataTableColumn<SampleRow>[] = [
  {
    id: 'player',
    header: 'Player',
    rowHeader: true,
    sortValue: (row) => row.name,
    cell: (row) => (
      <>
        <RowLink to={`?row=${row.id}`} preventScrollReset>
          {row.name}
        </RowLink>{' '}
        <span className="text-ink-muted text-detail whitespace-nowrap">
          {row.team} {row.opponent}
        </span>
      </>
    ),
  },
  { id: 'grade', header: 'Matchup', sortValue: (row) => row.grade, cell: (row) => row.grade },
  { id: 'note', header: 'Status', className: 'text-ink-secondary', cell: (row) => row.note },
  {
    id: 'floor',
    header: 'Floor',
    numeric: true,
    sortValue: (row) => (row.points === null ? null : row.floor),
    tip: 'A bad-but-realistic week. The player scores less than this about 1 week in 10.',
    cell: (row) => formatPoints(row.points === null ? null : row.floor),
  },
  {
    id: 'ceiling',
    header: 'Ceiling',
    numeric: true,
    sortValue: (row) => (row.points === null ? null : row.ceiling),
    cell: (row) => formatPoints(row.points === null ? null : row.ceiling),
  },
  {
    id: 'boom',
    header: 'Chance of 20+',
    numeric: true,
    sortValue: (row) => row.boom,
    cell: (row) => formatPercent(row.boom),
  },
  {
    id: 'points',
    header: 'Projection',
    numeric: true,
    sortValue: (row) => row.points,
    className: 'font-semibold',
    cell: (row) => formatPoints(row.points),
  },
]

const SORTABLE = COLUMNS.filter((column) => column.sortValue).map((column) => column.id)
const DEFAULT_STATE = { sort: 'points', dir: 'desc', density: 'default', row: '' }

const POSITION_OPTIONS = [{ value: '', label: 'All' }, ...['QB', 'RB', 'WR', 'TE'].map((p) => ({ value: p, label: p }))]
const DESIGNATION_OPTIONS = [
  { value: 'all', label: 'All' },
  { value: 'serious', label: 'Out & doubtful' },
  { value: 'questionable', label: 'Questionable' },
  { value: 'practice', label: 'Practice only' },
]

const VARIANTS: ButtonVariant[] = ['primary', 'secondary', 'ghost', 'danger', 'link']
const VARIANT_LABEL: Record<ButtonVariant, string> = {
  primary: 'Primary',
  secondary: 'Secondary',
  ghost: 'Ghost',
  danger: 'Remove all',
  link: 'Technical detail',
}
const SIZES: { size: ButtonSize; note: string }[] = [
  { size: 'md', note: '40px · a page’s primary action' },
  { size: 'sm', note: '32px · toolbars' },
  { size: 'xs', note: '28px · inside table rows' },
]

const TYPE: { token: string; role: string; sample: ReactNode }[] = [
  { token: 'text-hero', role: 'Hero number · 56px, proportional figures', sample: '19.4' },
  { token: 'text-title', role: 'Page title · 24px bold', sample: 'Rankings' },
  { token: 'text-section', role: 'Section title · 17px semibold', sample: 'Value against ADP' },
  { token: 'text-body', role: 'Body and table cell · 14px', sample: 'Jahmyr Gibbs is projected for 19.4 points.' },
  { token: 'text-detail', role: 'Secondary text · 13px', sample: 'RB · DET @ CAR · last four games' },
  { token: 'text-caption', role: 'Caption and column header · 12.5px', sample: 'Chance of 20+' },
  { token: 'text-chip', role: 'Chip and axis text · 11.5px', sample: 'A+ · Model · 20 pts' },
]

export default function SpecimensPage() {
  const [state, setState] = useUrlState(DEFAULT_STATE)
  const sort = parseSort(state.sort, state.dir, SORTABLE, { key: 'points', direction: 'desc' })
  const density = (['compact', 'default', 'comfortable'].includes(state.density) ? state.density : 'default') as TableDensity
  const [busy, setBusy] = useState(false)
  // The toolbar specimen keeps its own state: it shows the controls, and
  // filters nothing.
  const [query, setQuery] = useState('')
  const [position, setPosition] = useState('')
  const [designation, setDesignation] = useState('all')
  const [game, setGame] = useState(true)

  return (
    <>
      <PageHeader
        title="Specimens"
        question="Every shared part in every state, drawn with the real tokens. Sample data, not projections."
      />

      <div className="space-y-6">
        <Card>
          <CardHeader title="Type" description="Seven roles. A size that is not one of these needs a reason written beside it." />
          <CardBody className="space-y-3">
            {TYPE.map((row) => (
              <div key={row.token} className="border-line flex flex-wrap items-baseline gap-x-6 gap-y-1 border-b pb-3 last:border-b-0 last:pb-0">
                <span className={`text-ink ${row.token}`}>{row.sample}</span>
                <span className="text-ink-muted text-detail">
                  <code className="text-ink-secondary">{row.token}</code> · {row.role}
                </span>
              </div>
            ))}
          </CardBody>
        </Card>

        <Card>
          <CardHeader
            title="Radius, heights and elevation"
            description="Three radii and the pill, three control heights and the touch size, a hairline and two shadows."
          />
          <CardBody className="text-detail text-ink-secondary flex flex-wrap items-end gap-x-8 gap-y-5">
            <Swatch label="rounded-card · 10px" className="rounded-card h-16 w-28" />
            <Swatch label="rounded-control · 6px" className="rounded-control h-control w-28" />
            <Swatch label="rounded-chip · 4px" className="rounded-chip h-6 w-12" />
            <Swatch label="rounded-full · status only" className="h-6 w-20 rounded-full" />
            <Swatch label="h-control · 40" className="rounded-control h-control w-10" />
            <Swatch label="h-control-sm · 32" className="rounded-control h-control-sm w-10" />
            <Swatch label="h-control-xs · 28" className="rounded-control h-control-xs w-10" />
            <Swatch label="h-touch · 44" className="rounded-control h-touch w-10" />
            <Swatch label="hairline, no shadow" className="rounded-card h-16 w-28" />
            <Swatch label="shadow-raised" className="rounded-card shadow-raised h-16 w-28" />
            <Swatch label="shadow-overlay" className="rounded-card shadow-overlay h-16 w-28" />
          </CardBody>
        </Card>

        <Card>
          <CardHeader
            title="Buttons"
            description="One class builder under four components: Button, ButtonLink, IconButton, IconButtonLink."
          />
          <CardBody className="space-y-5">
            {SIZES.map(({ size, note }) => (
              <div key={size}>
                <p className="text-ink-muted text-caption mb-2">
                  <code>size="{size}"</code> · {note}
                </p>
                <div className="flex flex-wrap items-center gap-2">
                  {VARIANTS.map((variant) => (
                    <Button key={variant} variant={variant} size={size}>
                      {VARIANT_LABEL[variant]}
                    </Button>
                  ))}
                  <Button size={size} icon={<Copy aria-hidden />}>
                    Copy link
                  </Button>
                  <Button size={size} variant="primary" disabled>
                    Disabled
                  </Button>
                  <Button size={size} disabled>
                    Disabled
                  </Button>
                  <IconButton size={size} variant="secondary" label="Search">
                    <Search />
                  </IconButton>
                  <IconButton size={size} label="Remove player">
                    <Trash2 />
                  </IconButton>
                </div>
              </div>
            ))}

            <div>
              <p className="text-ink-muted text-caption mb-2">
                Loading keeps the width: the spinner takes the icon’s place, or the label’s when there is no icon. Press
                one.
              </p>
              <div className="flex flex-wrap items-center gap-2">
                <Button variant="primary" icon={<Play aria-hidden />} loading={busy} onClick={() => setBusy(true)}>
                  Run simulation
                </Button>
                <Button loading={busy} onClick={() => setBusy(true)}>
                  Show 100 more
                </Button>
                <Button variant="primary" size="sm" icon={<UserPlus aria-hidden />} loading>
                  Add to my team
                </Button>
                <Button size="sm" loading>
                  Load
                </Button>
                <IconButton label="Refreshing" variant="secondary" loading>
                  <Settings />
                </IconButton>
                <Button variant="ghost" size="sm" onClick={() => setBusy(false)}>
                  Reset
                </Button>
              </div>
            </div>

            <div>
              <p className="text-ink-muted text-caption mb-2">Links drawn as buttons. They navigate, so they have no disabled state.</p>
              <div className="flex flex-wrap items-center gap-2">
                <ButtonLink to="/my-team" variant="primary">
                  Add your roster
                  <ArrowRight aria-hidden />
                </ButtonLink>
                <ButtonLink to="/my-team">Edit lineup</ButtonLink>
                <ButtonLink to="/draft-board" variant="link" size="sm">
                  Run a mock draft on this pool
                </ButtonLink>
                <IconButtonLink to="/settings" label="Settings">
                  <Settings />
                </IconButtonLink>
              </div>
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              {(['light', 'dark'] as const).map((theme) => (
                <div key={theme} data-theme={theme} className="bg-bg border-line-strong rounded-card border p-4">
                  <p className="text-ink-muted text-caption mb-3">The {theme} palette, whatever the page is set to</p>
                  <div className="flex flex-wrap items-center gap-2">
                    <Button variant="primary" size="sm">
                      Primary
                    </Button>
                    <Button size="sm">Secondary</Button>
                    <Button variant="ghost" size="sm">
                      Ghost
                    </Button>
                    <Button variant="danger" size="sm">
                      Remove all
                    </Button>
                    <IconButton label="Close" variant="secondary">
                      <X />
                    </IconButton>
                    <Badge tone="positive">+4</Badge>
                    <Badge tone="caution">−3</Badge>
                  </div>
                </div>
              ))}
            </div>
          </CardBody>
        </Card>

        <Card>
          <CardHeader
            title="Filter toolbar"
            description="The controls that decide which rows a table holds: one height, wrapping between controls and never inside one, with the count at the trailing edge. It owns no state."
          />
          <CardBody className="space-y-5">
            <FilterToolbar label="Filter sample players" summary="12 of 36 players">
              <FilterSearch
                label="Search sample players"
                placeholder="Search by name or team…"
                value={query}
                onChange={setQuery}
              />
              <FilterChoice label="Position" value={position} onChange={setPosition} options={POSITION_OPTIONS} />
              <FilterChoice label="Designation" value={designation} onChange={setDesignation} options={DESIGNATION_OPTIONS} />
              {game && (
                <FilterChip removeLabel="Show every game, not just DET at CAR" onRemove={() => setGame(false)}>
                  DET @ CAR
                </FilterChip>
              )}
            </FilterToolbar>

            <div>
              <p className="text-ink-muted text-caption mb-2">
                The same toolbar given 20rem. The choice that no longer fits is drawn as a select; the one that fits
                is left alone.
              </p>
              <div data-narrow-toolbar className="border-line-strong rounded-control w-80 max-w-full border p-3">
                <FilterToolbar label="Filter sample players, narrow" summary="12 of 36 players" className="mb-0">
                  <FilterSearch
                    label="Search sample players, narrow"
                    placeholder="Search by name or team…"
                    value={query}
                    onChange={setQuery}
                  />
                  <FilterChoice label="Position" value={position} onChange={setPosition} options={POSITION_OPTIONS} />
                  <FilterChoice label="Designation" value={designation} onChange={setDesignation} options={DESIGNATION_OPTIONS} />
                </FilterToolbar>
              </div>
            </div>
          </CardBody>
        </Card>

        {/* `clip`, so the header can stick to the page rather than to the card. */}
        <Card className="overflow-clip">
          <CardHeader
            title="DataTable"
            description="Sort from any header with a button. Text sits left, numbers right in tabular figures. Click a row, or tab to its name and press Enter: the row is selected through the URL. Scroll the page and the header stays."
            action={
              <SegmentedControl
                label="Row height"
                size="sm"
                value={density}
                onChange={(value) => setState({ density: value })}
                options={[
                  { value: 'compact', label: 'Compact 32' },
                  { value: 'default', label: 'Default 40' },
                  { value: 'comfortable', label: 'Comfortable 48' },
                ]}
              />
            }
          />
          <DataTable
            caption="Sample running backs"
            columns={COLUMNS}
            rows={LONG_ROWS}
            rowKey={(row) => row.id}
            density={density}
            sort={sort}
            onSortChange={(next) => setState({ sort: next.key, dir: next.direction })}
            isSelected={(row) => row.id === state.row}
            minWidth="52rem"
            freezeFirstColumn
          />
        </Card>

        {/* `min-w-0`: a grid item is otherwise at least as wide as its table's
            columns, and at 360px these two pushed the page 41px wide. */}
        <div className="grid gap-6 lg:grid-cols-2">
          <Card className="min-w-0 overflow-clip">
            <CardHeader title="Loading" description="Placeholder rows at the real row height, under the real header." />
            <DataTable caption="Sample table, loading" columns={COLUMNS.slice(0, 1).concat(COLUMNS.slice(3))} rows={[]} rowKey={(row) => row.id} loading loadingRows={4} stickyHeader={false} minWidth="23rem" freezeFirstColumn />
          </Card>
          <Card className="min-w-0 overflow-clip">
            <CardHeader title="Empty" description="The header stays, and the body says why there is nothing." />
            <DataTable
              caption="Sample table, empty"
              columns={COLUMNS.slice(0, 1).concat(COLUMNS.slice(3))}
              rows={[]}
              rowKey={(row) => row.id}
              stickyHeader={false}
              minWidth="23rem"
              freezeFirstColumn
              empty={<EmptyState title="No players match" description="Nothing on the board fits this position and lens." className="py-8" />}
            />
          </Card>
        </div>

        <Card className="overflow-clip">
          <CardHeader
            title="Narrow frame"
            description="The same table given 22rem. It scrolls inside its own frame, the header stays at the top and the player column stays at the left. Nothing is hidden to make it fit."
          />
          <CardBody>
            <div className="border-line-strong rounded-control w-88 max-w-full overflow-clip border">
              <DataTable
                caption="Sample running backs, narrow"
                columns={COLUMNS}
                rows={ROWS}
                rowKey={(row) => row.id}
                density="compact"
                minWidth="46rem"
                freezeFirstColumn
                className="max-h-72"
              />
            </div>
          </CardBody>
        </Card>

        <Card className="overflow-clip">
          <CardHeader
            title="Composed from parts"
            description="Row groups with their own headings, which the column-definition form does not cover. Same parts, same look."
          />
          <Table caption="Sample running backs by tier" stickyHeader={false}>
            <TableHead>
              <ColumnHeader>Player</ColumnHeader>
              <ColumnHeader>Matchup</ColumnHeader>
              <ColumnHeader numeric>Projection</ColumnHeader>
              <ColumnHeader>
                <span className="sr-only">Actions</span>
              </ColumnHeader>
            </TableHead>
            {[1, 2, 3].map((tier) => {
              const members = ROWS.filter((row) => row.tier === tier).slice(0, 3)
              return (
                <TableBody key={tier}>
                  <GroupHeaderRow colSpan={4}>
                    Tier {tier} <span className="text-ink-muted ml-2 font-normal">{members.length} shown</span>
                  </GroupHeaderRow>
                  {members.map((row) => (
                    // A marked row: tinted, and said in words beside the name.
                    <TableRow key={row.id} selected={row.id === state.row} highlighted={row.id === 'r03'}>
                      <RowHeaderCell>
                        <RowLink to={`?row=${row.id}`} preventScrollReset>
                          {row.name}
                        </RowLink>{' '}
                        <span className="text-ink-muted text-detail">
                          {row.team} {row.opponent}
                        </span>
                        {row.id === 'r03' && <span className="text-accent-text text-detail ml-2 font-medium">My team</span>}
                      </RowHeaderCell>
                      <TableCell>{row.grade}</TableCell>
                      <TableCell numeric className="font-semibold">
                        {formatPoints(row.points)}
                      </TableCell>
                      <TableCell className="w-px text-right whitespace-nowrap">
                        {/* A control of its own inside a linked row: pressing
                            it does its own thing and does not follow the row. */}
                        <Button size="xs">Bench</Button>{' '}
                        <IconButton size="xs" label={`Remove ${row.name}`}>
                          <Trash2 />
                        </IconButton>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              )
            })}
          </Table>
        </Card>
      </div>
    </>
  )
}

function Swatch({ label, className }: { label: string; className: string }) {
  return (
    <div className="flex flex-col items-start gap-1.5">
      <span className={`bg-surface border-line-strong border ${className}`} />
      <span>{label}</span>
    </div>
  )
}
