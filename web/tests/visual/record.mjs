/**
 * Re-record the API fixtures the screenshot tests replay, then accept the
 * pictures they produce as the new baselines.
 *
 * Two passes because a recording is written when its browser context closes:
 * the first pass visits every screen against the live local API and saves what
 * it was served; the second replays those archives and takes the pictures.
 *
 * Needs the local API (`python -m nflfp.api --port 8010`) and a current
 * `npm run build`. One worker, so both viewports agree on who is on screen.
 *
 * With screen names (`node tests/visual/record.mjs specimens draft-board`) only
 * those are re-recorded, and with `--project visual-tablet` only at that width. Every other archive, picture and the chosen players
 * stay exactly as they are — which is what adding a screen should cost.
 */
import { spawnSync } from 'node:child_process'
import { readdirSync, rmSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const ALL_PROJECTS = ['visual-desktop', 'visual-tablet', 'visual-mobile']

// `--project visual-tablet` (repeatable) limits the run to those viewports: a
// screen newly photographed at one width is recorded there without disturbing
// what the other widths already replay.
const argv = process.argv.slice(2)
const chosen = argv.flatMap((arg, index) => (arg === '--project' && argv[index + 1] ? [argv[index + 1]] : []))
const only = argv.filter((arg, index) => arg !== '--project' && argv[index - 1] !== '--project')
const projectNames = chosen.length ? chosen : ALL_PROJECTS
const projects = projectNames.map((name) => `--project=${name}`)

function run(args, env = {}) {
  const result = spawnSync('npx', ['playwright', 'test', ...projects, ...args], {
    stdio: 'inherit',
    shell: true,
    env: { ...process.env, ...env },
  })
  if (result.status !== 0) process.exit(result.status ?? 1)
}

if (only.length === 0) {
  // Old archives would be merged into, and a screen that stopped calling an
  // endpoint would keep its stale response.
  rmSync(join(here, 'fixtures'), { recursive: true, force: true })

  run(['--workers=1'], { VISUAL_RECORD: '1' })
  run(['--update-snapshots'])
} else {
  // A test is titled "<screen>, <theme>", after the project and file names.
  const grep = ['-g', `" (${only.join('|')}), (light|dark)"`]
  for (const name of only) {
    for (const archive of readdirSync(join(here, 'fixtures'))) {
      // `<screen>-<theme>.<project>.zip`. Matched whole, so `team` does not
      // take `my-team` with it, and only for the viewports being recorded.
      const match = archive.match(/^(.+)-(?:light|dark)\.([\w-]+)\.zip$/)
      if (match && match[1] === name && projectNames.includes(match[2])) rmSync(join(here, 'fixtures', archive))
    }
  }
  run(['--workers=1', ...grep], { VISUAL_RECORD: '1', VISUAL_KEEP_SUBJECTS: '1' })
  run(['--update-snapshots', ...grep])
}
