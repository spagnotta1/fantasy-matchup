/**
 * The one place that talks to the network.
 *
 * Everything above this file consumes typed functions and never sees a URL, a
 * status code or a JSON body. That is what makes the error story consistent:
 * the API has exactly one error shape (`{code, message, field, remedy}`), so
 * there is exactly one place that turns it into something a person can read.
 *
 * A note on `remedy`. The backend fills it with an *operator* action — "run
 * `jobs run build_features`". That is genuinely useful and must never reach a
 * fantasy manager, so it is carried on the error object and rendered only
 * behind a developer affordance.
 */

import { z } from 'zod'

import { errorBodySchema, envelope, type Envelope } from './schemas'

/** Same-origin by default; Vite proxies `/api` to the backend in development. */
export const API_BASE = import.meta.env.VITE_API_BASE_URL ?? ''
export const API_PREFIX = '/api/v1'

/** How long we wait before deciding the API is not going to answer. */
const DEFAULT_TIMEOUT_MS = 15_000
/** A simulation holds a worker for the whole Monte Carlo run. */
export const LONG_TIMEOUT_MS = 60_000

export type QueryValue = string | number | boolean | null | undefined | Array<string | number>

/**
 * A failed request, normalised.
 *
 * `kind` is what the UI branches on. It separates the three cases that need
 * genuinely different copy: the network never answered, the server is in a
 * recoverable state, or the request itself was wrong.
 */
export class ApiError extends Error {
  readonly kind: 'network' | 'timeout' | 'unavailable' | 'not_found' | 'invalid' | 'server' | 'contract'
  readonly status: number | null
  readonly code: string
  readonly field: string | null
  /** Operator remediation. Never render this to an end user. */
  readonly remedy: string | null
  readonly retryAfterSeconds: number | null

  constructor(init: {
    kind: ApiError['kind']
    message: string
    status?: number | null
    code?: string
    field?: string | null
    remedy?: string | null
    retryAfterSeconds?: number | null
    cause?: unknown
  }) {
    super(init.message, init.cause ? { cause: init.cause } : undefined)
    this.name = 'ApiError'
    this.kind = init.kind
    this.status = init.status ?? null
    this.code = init.code ?? init.kind
    this.field = init.field ?? null
    this.remedy = init.remedy ?? null
    this.retryAfterSeconds = init.retryAfterSeconds ?? null
  }

  /** Whether trying the exact same request again could plausibly work. */
  get isRetryable(): boolean {
    return this.kind === 'network' || this.kind === 'timeout' || this.kind === 'unavailable' || this.kind === 'server'
  }
}

function kindForStatus(status: number): ApiError['kind'] {
  if (status === 404) return 'not_found'
  if (status === 422 || status === 400) return 'invalid'
  if (status === 503) return 'unavailable'
  return 'server'
}

/** Build a query string, dropping empties and repeating array params. */
export function buildQuery(params: Record<string, QueryValue> | undefined): string {
  if (!params) return ''
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined || value === '') continue
    if (Array.isArray(value)) {
      // The API declares list params as repeated keys (`?positions=RB&positions=WR`),
      // which is what FastAPI parses. A comma-joined string is a different request.
      for (const item of value) search.append(key, String(item))
      continue
    }
    search.append(key, String(value))
  }
  const query = search.toString()
  return query ? `?${query}` : ''
}

interface RequestOptions {
  method?: 'GET' | 'POST'
  params?: Record<string, QueryValue>
  body?: unknown
  signal?: AbortSignal
  timeoutMs?: number
}

/**
 * Perform a request and validate the envelope.
 *
 * @param path Path below `/api/v1`, e.g. `/projections`.
 * @param dataSchema Validator for the `data` member of the envelope.
 */
export async function request<T extends z.ZodTypeAny>(
  path: string,
  dataSchema: T,
  options: RequestOptions = {},
): Promise<Envelope<z.infer<T>>> {
  const payload = await fetchJson(path, options)
  return validate(envelope(dataSchema), payload, path) as Envelope<z.infer<T>>
}

/**
 * A request whose response is *not* enveloped.
 *
 * The three health endpoints return `HealthOut` bare rather than in
 * `{data, meta}` — they are read by load balancers, which should not have to
 * unwrap anything. This is the only exception in the API.
 */
export async function requestBare<T extends z.ZodTypeAny>(
  path: string,
  schema: T,
  options: RequestOptions = {},
): Promise<z.infer<T>> {
  const payload = await fetchJson(path, options)
  return validate(schema, payload, path)
}

/** Everything up to and including the HTTP error mapping. Returns raw JSON. */
async function fetchJson(path: string, options: RequestOptions): Promise<unknown> {
  const { method = 'GET', params, body, signal, timeoutMs = DEFAULT_TIMEOUT_MS } = options
  const url = `${API_BASE}${API_PREFIX}${path}${buildQuery(params)}`

  // Compose the caller's cancellation with our own deadline, so unmounting a
  // component and timing out are the same code path downstream.
  const timeout = AbortSignal.timeout(timeoutMs)
  const composed = signal ? AbortSignal.any([signal, timeout]) : timeout

  let response: Response
  try {
    response = await fetch(url, {
      method,
      signal: composed,
      headers: {
        Accept: 'application/json',
        ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
      },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    })
  } catch (cause) {
    if (signal?.aborted) throw cause
    const timedOut = timeout.aborted
    throw new ApiError({
      kind: timedOut ? 'timeout' : 'network',
      code: timedOut ? 'timeout' : 'network_error',
      message: timedOut
        ? 'The request took too long to complete.'
        : 'Could not reach the projections service.',
      cause,
    })
  }

  if (!response.ok) {
    const parsed = errorBodySchema.safeParse(await readJson(response))
    const retryAfter = Number(response.headers.get('Retry-After'))
    throw new ApiError({
      kind: kindForStatus(response.status),
      status: response.status,
      code: parsed.success ? parsed.data.code : `http_${response.status}`,
      message: parsed.success ? parsed.data.message : 'The service returned an unexpected error.',
      field: parsed.success ? (parsed.data.field ?? null) : null,
      remedy: parsed.success ? (parsed.data.remedy ?? null) : null,
      retryAfterSeconds: Number.isFinite(retryAfter) && retryAfter > 0 ? retryAfter : null,
    })
  }

  return readJson(response)
}

/** Validate a payload, turning a schema mismatch into a `contract` error. */
function validate<T extends z.ZodTypeAny>(schema: T, payload: unknown, path: string): z.infer<T> {
  const result = schema.safeParse(payload)
  if (!result.success) {
    // A shape we did not compile against. Loud in development, and a generic
    // failure in production — a Zod issue path is not user-facing copy.
    if (import.meta.env.DEV) {
      console.error(`[api] response did not match the contract for ${path}`, result.error.issues)
    }
    throw new ApiError({
      kind: 'contract',
      code: 'unexpected_response',
      message: 'The service returned data in an unexpected format.',
      cause: result.error,
    })
  }
  return result.data
}

async function readJson(response: Response): Promise<unknown> {
  try {
    return await response.json()
  } catch {
    return null
  }
}

/**
 * User-facing copy for a failure.
 *
 * Deliberately not a lookup on `error.message`: the API's messages are written
 * for a developer reading a log, and several of them name database relations.
 * The mapping is on `kind` and `code`, which are stable.
 */
export function presentError(error: unknown): {
  title: string
  description: string
  canRetry: boolean
  operatorDetail: string | null
} {
  if (!(error instanceof ApiError)) {
    return {
      title: 'Something went wrong',
      description: 'An unexpected problem stopped this from loading. Try again in a moment.',
      canRetry: true,
      operatorDetail: error instanceof Error ? error.message : null,
    }
  }

  const operatorDetail = error.remedy ?? (import.meta.env.DEV ? error.message : null)

  switch (error.kind) {
    case 'network':
      return {
        title: "Can't reach the service",
        description:
          'Your device is online but the projections service did not respond. This is usually temporary.',
        canRetry: true,
        operatorDetail,
      }
    case 'timeout':
      return {
        title: 'This is taking longer than expected',
        description: 'The request timed out before the service answered. Try again.',
        canRetry: true,
        operatorDetail,
      }
    case 'unavailable':
      return {
        title: 'This data is being rebuilt',
        description:
          "The weekly data behind this view hasn't finished publishing yet. It usually returns within a few minutes.",
        canRetry: true,
        operatorDetail,
      }
    case 'not_found':
      return {
        title: 'Not found',
        description: "We couldn't find what you were looking for. It may have moved or never existed.",
        canRetry: false,
        operatorDetail,
      }
    case 'invalid':
      // 422 from this API is semantic — "kickers are not projected yet" — and
      // its message is written to be read. This is the one case where passing
      // the server's own words through is the honest thing to do.
      return {
        title: "That request can't be answered",
        description: error.message,
        canRetry: false,
        operatorDetail,
      }
    case 'contract':
      return {
        title: 'Unexpected response',
        description: 'The service replied with something this version of the app cannot read.',
        canRetry: true,
        operatorDetail,
      }
    default:
      return {
        title: 'Something went wrong on our end',
        description: 'The service hit an unexpected problem. Try again shortly.',
        canRetry: true,
        operatorDetail,
      }
  }
}
