"""A small in-memory cache for feed answers - issue #191, part 6.

Each running Lambda keeps its own copy for as long as it stays warm. Nothing
is shared between Lambdas and nothing survives a cold start; a shared cache
needs AWS, which is part 7.

What goes in is whatever an adapter stores after it has fully read and
checked an answer. An answer that failed or could not be read is never
stored, so a cache can make an answer older but never wrong. Cached values
are shared between requests and must be treated as read-only.
"""
from collections import OrderedDict, namedtuple
from datetime import datetime, timedelta, timezone

# What a feed adapter's fetch_events returns. retrieved_at is when the feed
# actually answered, which for a cached answer is earlier than the request.
# stale is True when the feed could not be reached and an older answer, still
# inside the feed's limit, was used instead.
FeedAnswer = namedtuple("FeedAnswer", "events retrieved_at stale")

Cached = namedtuple("Cached", "value fetched_at stale")

_CACHES = []


def utcnow():
    """The one clock for disaster_check, the feeds and their caches.

    Tests set the time by patching this function.
    """
    return datetime.now(timezone.utc)


class Unreachable(Exception):
    """The feed could not be reached: a network error, a timeout or an HTTP error.

    Only this kind of failure lets an older answer stand in. A feed that did
    answer, with something that could not be read or was incomplete, may be
    saying something new - a flood the older answer does not have - so an
    older answer must not be used in its place.
    """


class BackingOff(Exception):
    """The feed failed moments ago and is not being asked again yet."""


class FeedCache:
    """Answers kept by key, with a fresh time, a stale limit and a pause after failure.

    - ``fresh_seconds``: how long an answer is used without asking again.
    - ``stale_seconds``: if the feed cannot be reached, an answer up to this
      old is used instead, marked stale. Zero means never.
    - ``retry_seconds``: after a failure the feed is not asked again for this
      long, so callers get an answer at once instead of each waiting out a
      timeout. Paused per key.
    - ``max_entries``: beyond this, the least recently used answer is dropped.
    """

    def __init__(self, fresh_seconds, stale_seconds=0, retry_seconds=60, max_entries=8):
        self.fresh = timedelta(seconds=fresh_seconds)
        self.stale = timedelta(seconds=stale_seconds)
        self.retry = timedelta(seconds=retry_seconds)
        self.max_entries = max_entries
        self._entries = OrderedDict()
        # key -> (when it failed, whether the feed was unreachable)
        self._failed = {}
        _CACHES.append(self)

    def get(self, key, fetch):
        """The answer for ``key``: cached if fresh, else from ``fetch()``.

        Raises whatever ``fetch`` raises, or BackingOff during the pause after
        a failure, unless the feed was unreachable and an answer inside the
        stale limit can stand in.
        """
        now = utcnow()
        entry = self._entries.get(key)
        if entry is not None and _within(now - entry.fetched_at, self.fresh):
            self._entries.move_to_end(key)
            return entry

        failure = self._failed.get(key)
        if failure is not None:
            failed_at, unreachable = failure
            if _within(now - failed_at, self.retry, inclusive=False):
                paused = BackingOff(f"{key!r} failed at {failed_at:%H:%M:%S}")
                return self._stale_or_raise(key, entry, now, paused, unreachable)
            del self._failed[key]

        try:
            value = fetch()
        except Exception as e:
            unreachable = isinstance(e, Unreachable)
            self._failed[key] = (now, unreachable)
            return self._stale_or_raise(key, entry, now, e, unreachable)

        # Stamped when the answer arrived, not when it was asked for.
        entry = Cached(value, utcnow(), False)
        self._entries[key] = entry
        self._entries.move_to_end(key)
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)
        return entry

    def _stale_or_raise(self, key, entry, now, error, unreachable):
        # Only reached once an answer is past its fresh time, so a stale limit
        # no longer than the fresh time never lets an old answer through.
        if unreachable and entry is not None and _within(now - entry.fetched_at, self.stale):
            print(f"WARN: feed answer for {key!r} could not be refreshed ({type(error).__name__}); "
                  f"using the one from {entry.fetched_at:%Y-%m-%dT%H:%M:%SZ}")
            return entry._replace(stale=True)
        raise error

    def clear(self):
        self._entries.clear()
        self._failed.clear()


def clear_all():
    """Empty every cache. Tests do this before each test."""
    for cache in _CACHES:
        cache.clear()


def _within(age, limit, inclusive=True):
    # A negative age means the clock went backwards. Nothing is trusted then.
    if age < timedelta(0):
        return False
    return age <= limit if inclusive else age < limit
