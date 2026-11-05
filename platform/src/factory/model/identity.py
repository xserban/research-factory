import re
import secrets
from datetime import UTC, datetime, timedelta

from factory.clock import Clock

ULID_RE = r"[0-9A-HJKMNP-TV-Z]{26}"
ACTOR_ID_RE = r"^[a-z0-9][a-z0-9._-]{0,63}$"
SLUG_RE = r"^[a-z0-9]+(-[a-z0-9]+)*$"
BLOB_REF_RE = r"^sha256:[0-9a-f]{64}$"
CONVERSION_ID_RE = rf"^cnv_{ULID_RE}$"

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_RANDOM_BITS = 80
_ONE_MS = timedelta(milliseconds=1)


def _encode(value: int) -> str:
    return "".join(_ALPHABET[(value >> (5 * shift)) & 31] for shift in range(25, -1, -1))


def _decode(text: str) -> int:
    value = 0
    for char in text:
        value = (value << 5) | _ALPHABET.index(char)
    return value


class IdGenerator:
    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._last: int | None = None

    def ulid(self) -> str:
        ms = (self._clock.now() - _EPOCH) // _ONE_MS
        if self._last is not None and ms <= (self._last >> _RANDOM_BITS):
            value = self._last + 1
        else:
            value = (ms << _RANDOM_BITS) | secrets.randbits(_RANDOM_BITS)
        self._last = value
        return _encode(value)

    def floor(self, ulid: str) -> None:
        """Make every later `ulid()` strictly greater than `ulid`, whatever the clock says. Never
        lowers the generator: the floor of a session that minted higher is a no-op."""
        if not re.fullmatch(ULID_RE, ulid):
            raise ValueError(f"not a ULID: {ulid!r}")
        value = _decode(ulid)
        self._last = value if self._last is None else max(self._last, value)

    def new(self, prefix: str) -> str:
        return f"{prefix}_{self.ulid()}"


def ulid_time(ulid: str) -> datetime:
    if not re.fullmatch(ULID_RE, ulid):
        raise ValueError(f"not a ULID: {ulid!r}")
    ms = _decode(ulid) >> _RANDOM_BITS
    return _EPOCH + ms * _ONE_MS


def is_prefixed_id(value: str, prefix: str) -> bool:
    return re.fullmatch(rf"{re.escape(prefix)}_{ULID_RE}", value) is not None
