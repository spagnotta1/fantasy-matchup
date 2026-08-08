"""Minimal JSON-over-HTTP client with retry, backoff and logging.

Why not ``requests`` or ``httpx``
---------------------------------
The existing ingest already speaks to GitHub's API through :mod:`urllib` with
no third-party HTTP dependency, and the two providers added here need exactly
one verb (GET) returning exactly one content type (JSON). Adding a dependency —
and a second set of timeout, proxy and TLS semantics — to save thirty lines is
not a trade worth making in a service that has to stay up on a Sunday morning.

What this does add over raw ``urlopen``:

* a **bounded** retry budget with exponential backoff and jitter, applied only
  to errors that retrying can fix;
* ``Retry-After`` support, so a 429 waits the interval the server asked for
  rather than the one we guessed;
* a total deadline, so a provider cannot hold a scheduled job open indefinitely;
* structured logging of every attempt, because a provider that silently
  degrades is worse than one that fails.
"""

from __future__ import annotations

import json
import logging
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from .errors import (
    PermanentProviderError,
    ProviderValidationError,
    TransientProviderError,
)

logger = logging.getLogger(__name__)

# Status codes worth trying again. 429 is rate limiting; 5xx is the upstream
# having a bad time. Everything else is our fault and will stay our fault.
RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})

# Some upstreams (ESPN in particular) return 403 to unrecognised clients. A
# browser-shaped User-Agent is the difference between working and not; this was
# verified empirically, and a short "Mozilla/5.0" is *not* sufficient.
DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) nflfp/0.1"


@dataclass(frozen=True)
class RetryPolicy:
    """Bounded exponential backoff with full jitter.

    Jitter matters even for a single-instance job: without it, a provider that
    briefly 503s gets hit by every retry in lockstep, which is how a blip
    becomes a ban.
    """

    attempts: int = 4
    backoff_base: float = 0.5
    backoff_max: float = 20.0
    deadline: float = 90.0
    jitter: bool = True

    def sleep_for(self, attempt: int, retry_after: float | None = None) -> float:
        """Seconds to wait before `attempt` (1-based); honours ``Retry-After``."""
        if retry_after is not None:
            return min(retry_after, self.backoff_max)
        delay = min(self.backoff_base * (2 ** (attempt - 1)), self.backoff_max)
        return random.uniform(0, delay) if self.jitter else delay


@dataclass
class JsonHttpClient:
    """A GET-only JSON client carrying a retry policy and default headers."""

    user_agent: str = DEFAULT_USER_AGENT
    timeout: float = 20.0
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    headers: dict[str, str] = field(default_factory=dict)
    provider_name: str = "http"
    #: Injectable for tests — anything with urlopen(request, timeout) -> file.
    opener: Any = None
    #: Injectable for tests, so retry behaviour can be asserted without waiting.
    sleeper: Any = time.sleep

    def get_json(self, url: str, params: dict[str, Any] | None = None) -> Any:
        """GET `url` and parse the response as JSON.

        Args:
            url: Absolute URL.
            params: Query parameters, appended to any already in `url`.

        Returns:
            The decoded JSON payload.

        Raises:
            TransientProviderError: retries exhausted, or the deadline passed.
            PermanentProviderError: a status retrying cannot fix.
            ProviderValidationError: the body was not valid JSON.
        """
        full_url = _with_params(url, params)
        started = time.monotonic()
        last_error: Exception | None = None

        for attempt in range(1, self.retry.attempts + 1):
            elapsed = time.monotonic() - started
            if elapsed > self.retry.deadline:
                raise TransientProviderError(
                    f"deadline of {self.retry.deadline}s exceeded after "
                    f"{attempt - 1} attempt(s): {last_error}",
                    provider=self.provider_name,
                )
            try:
                return self._attempt(full_url, attempt)
            except PermanentProviderError:
                raise
            except ProviderValidationError:
                raise
            except TransientProviderError as exc:
                last_error = exc
                if attempt == self.retry.attempts:
                    break
                delay = self.retry.sleep_for(attempt, getattr(exc, "retry_after", None))
                logger.warning(
                    "%s: attempt %d/%d failed (%s); retrying in %.1fs",
                    self.provider_name, attempt, self.retry.attempts, exc, delay,
                )
                self.sleeper(delay)

        raise TransientProviderError(
            f"giving up after {self.retry.attempts} attempts: {last_error}",
            provider=self.provider_name,
        )

    # -- internals ---------------------------------------------------------

    def _attempt(self, url: str, attempt: int) -> Any:
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "application/json",
                **self.headers,
            },
        )
        opener = self.opener or urllib.request
        try:
            with opener.urlopen(request, timeout=self.timeout) as response:
                body = response.read()
        except urllib.error.HTTPError as exc:
            retry_after = _parse_retry_after(exc.headers.get("Retry-After"))
            if exc.code in RETRYABLE_STATUS:
                error = TransientProviderError(
                    f"HTTP {exc.code} from {_redact(url)}", provider=self.provider_name
                )
                error.retry_after = retry_after  # type: ignore[attr-defined]
                raise error from exc
            raise PermanentProviderError(
                f"HTTP {exc.code} from {_redact(url)}", provider=self.provider_name
            ) from exc
        except urllib.error.URLError as exc:
            raise TransientProviderError(
                f"connection error for {_redact(url)}: {exc.reason}",
                provider=self.provider_name,
            ) from exc
        except TimeoutError as exc:
            raise TransientProviderError(
                f"timed out after {self.timeout}s for {_redact(url)}",
                provider=self.provider_name,
            ) from exc

        logger.debug("%s: GET %s ok on attempt %d", self.provider_name, _redact(url), attempt)
        try:
            return json.loads(body)
        except (ValueError, UnicodeDecodeError) as exc:
            raise ProviderValidationError(
                f"response from {_redact(url)} was not valid JSON: {exc}",
                provider=self.provider_name,
            ) from exc


def _with_params(url: str, params: dict[str, Any] | None) -> str:
    if not params:
        return url
    parts = urllib.parse.urlsplit(url)
    merged = dict(urllib.parse.parse_qsl(parts.query))
    merged.update({k: str(v) for k, v in params.items() if v is not None})
    return urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(merged)))


def _parse_retry_after(value: str | None) -> float | None:
    """Parse a ``Retry-After`` header expressed in seconds.

    The HTTP-date form is deliberately unsupported: it is rare in JSON APIs, and
    guessing wrong is worse than falling back to our own backoff.
    """
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None


def _redact(url: str) -> str:
    """Strip credential-shaped query parameters before logging a URL.

    Provider URLs carry API keys in the query string, and logs get shipped
    somewhere less trusted than the process that wrote them.
    """
    parts = urllib.parse.urlsplit(url)
    if not parts.query:
        return url
    pairs = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    cleaned = [
        (k, "***" if any(s in k.lower() for s in ("key", "token", "secret", "pass")) else v)
        for k, v in pairs
    ]
    return urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(cleaned)))
