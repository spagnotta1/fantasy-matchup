# Railway service configs

One image, several services. Each file here is the `railway.json` for one
service; point a Railway service's **Settings → Config-as-code** at the path
below and it deploys with that start command and schedule.

| file | service | shape | schedule |
|---|---|---|---|
| `../railway.json` | **api** | always on, health-checked | — |
| `railway.pipeline.json` | nflverse warehouse refresh | cron, exits | `0 12 * * 2` |
| `railway.build-features.json` | rebuild feature views | cron, exits | `0 13 * * 2` |
| `railway.generate-projections.json` | fit and publish the slate | cron, exits | `0 14 * * 2` |
| `railway.evaluate-model.json` | re-measure the live model | cron, exits | `0 16 * * 3` |
| `railway.refresh-odds.json` | market snapshots | cron, exits | `15 * * * *` |
| `railway.refresh-weather.json` | forecast snapshots | cron, exits | `30 */6 * * *` |
| `railway.refresh-injuries.json` | daily injury report reload | cron, exits | `0 11 * * *` |
| `railway.refresh-features.json` | concurrent matview refresh | cron, exits | `45 * * * *` |
| `railway.warm-cache.json` | pre-render the boards | cron, exits | `20 * * * *` |

The Tuesday chain runs in dependency order — warehouse, then features, then
projections — with an hour of slack between each. The gaps are deliberate: a
step that overruns must not have the next one start against half-loaded data.

## These files are generated

Every file except `railway.pipeline.json` is written by

```powershell
python -m nflfp.jobs schedule --emit deploy/
```

Cadence is declared once, in `src/nflfp/jobs/registry.py`. Editing a
`cronSchedule` here instead will be overwritten the next time somebody
regenerates, and — worse — the deployed schedule and the one the code documents
would disagree in the meantime. Change the registry, regenerate, commit both.
`tests/test_jobs.py` asserts the two agree.

`invalidate_cache` deliberately has **no** file. It is a registered job with no
cadence: a cron that periodically threw the cache away would be a slow leak of
the benefit it exists to provide. Run it by hand after a data correction that
changes what an already-published run joins against.

```powershell
railway run python -m nflfp.jobs run invalidate_cache
```

## Variables

Set these on every service, as **references** rather than literals so they keep
working when credentials rotate:

| variable | value | who needs it |
|---|---|---|
| `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` | everything |
| `REDIS_URL` | `${{Redis.REDIS_URL}}` | api, warm-cache, generate-projections |
| `ENVIRONMENT` | `production` | everything — drives JSON logs and TLS expectations |
| `LOG_JSON` | `true` | everything |

`generate-projections` needs `REDIS_URL` because publishing retires the cache
namespace. Without it the publish still succeeds and logs that the epoch could
not be bumped, and the stale board expires on its TTL instead — degraded, not
broken, which is the intended failure mode.

### Sizing the connection pool

`DB_POOL_SIZE` × (replicas + concurrently running jobs) must stay under the
Postgres connection limit. Railway's starter Postgres allows far fewer
connections than the default pool size suggests, and the failure arrives as
`FATAL: too many connections` on the API — the service that was working — while
the job that exhausted the budget succeeds.

The cron services are the ones to watch: they are invisible between runs and
then all start within an hour of each other on a Tuesday.

## First deploy

```powershell
railway link
railway add --database postgres
railway add --database redis
railway up
```

Then, once, by hand — the crons only ever do incremental work:

```powershell
railway run python -m nflfp.pipeline full          # ~1.8M rows
railway run alembic upgrade head                   # application tables
railway run python -m nflfp.jobs run build_features
railway run python -m nflfp.jobs run generate_projections --publish
```

Until that sequence completes, every endpoint returns `503` naming the command
it is waiting on. That is by design — a fresh deployment where the default week
cannot resolve should say "run the pipeline", not "internal server error".
