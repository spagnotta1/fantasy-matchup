"""Provider error taxonomy.

The split that matters is **transient vs permanent**, because it is the only
thing the retry logic can act on. Retrying a 500 or a dropped socket is
correct; retrying a 401 burns quota and delays the log line that tells you the
API key is wrong.

Everything a provider raises should be one of these, so callers never have to
catch bare ``Exception`` to distinguish "try again in a minute" from "this will
never work".
"""

from __future__ import annotations


class ProviderError(RuntimeError):
    """Base class for every provider failure."""

    def __init__(self, message: str, *, provider: str | None = None) -> None:
        super().__init__(message)
        self.provider = provider


class TransientProviderError(ProviderError):
    """A failure that is plausibly fixed by trying again.

    Timeouts, connection resets, 429s and 5xx responses. The retry policy in
    :mod:`nflfp.providers.http` acts on exactly this type.
    """


class PermanentProviderError(ProviderError):
    """A failure retrying cannot fix.

    Authentication failures, 404s, malformed URLs. Raised immediately, without
    consuming the retry budget.
    """


class ProviderValidationError(ProviderError):
    """The upstream responded successfully but the payload was unusable.

    Kept separate from the transport errors because it means the *contract*
    changed — a field vanished, a type flipped, a number left its plausible
    range. That is a code change, not an outage, and the log line should say so.
    """
