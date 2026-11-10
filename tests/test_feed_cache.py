"""The feed cache - issue #191, part 6.

``FeedCache`` sits between disaster_check's feeds and USGS and GDACS. The
properties that keep it safe: a cached answer is never presented as newer
than it is, an answer that failed is never stored, an older answer stands in
only inside the limit it was given, and after a failure callers are answered
at once instead of each waiting out a timeout.
"""
from datetime import datetime, timedelta, timezone
from unittest import mock

import pytest

from services import feed_cache, gdacs_floods, usgs_earthquakes

pytestmark = pytest.mark.unit

T0 = datetime(2026, 10, 26, 12, 0, 0, tzinfo=timezone.utc)


class _Clock:
    def __init__(self):
        self.now = T0

    def __call__(self):
        return self.now

    def advance(self, **elapsed):
        self.now += timedelta(**elapsed)


@pytest.fixture
def clock():
    clock = _Clock()
    with mock.patch.object(feed_cache, "utcnow", clock):
        yield clock


class _Feed:
    """A fetch function that answers from a script of replies and counts calls."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = 0

    def __call__(self):
        self.calls += 1
        reply = self.replies.pop(0)
        if isinstance(reply, BaseException):
            raise reply
        return reply


def _cache(**limits):
    settings = {"fresh_seconds": 60, "stale_seconds": 0, "retry_seconds": 30, "max_entries": 8}
    return feed_cache.FeedCache(**{**settings, **limits})


class _Down(feed_cache.Unreachable):
    """The feed could not be reached."""


DOWN = _Down("feed down")
UNREADABLE = ValueError("the feed answered with something unreadable")


# -------------------------------------------------------------------------
# Fresh answers
# -------------------------------------------------------------------------

def test_a_fresh_answer_is_reused_without_asking_again(clock):
    cache, feed = _cache(), _Feed(["quake"])
    first = cache.get("k", feed)
    clock.advance(seconds=60)
    second = cache.get("k", feed)
    assert feed.calls == 1
    assert second == first
    assert (second.value, second.fetched_at, second.stale) == (["quake"], T0, False)


def test_an_answer_past_its_fresh_time_is_fetched_again(clock):
    cache, feed = _cache(), _Feed(["old"], ["new"])
    cache.get("k", feed)
    clock.advance(seconds=61)
    answer = cache.get("k", feed)
    assert feed.calls == 2
    assert (answer.value, answer.fetched_at) == (["new"], T0 + timedelta(seconds=61))


def test_answers_are_kept_by_key(clock):
    cache = _cache()
    cache.get("a", _Feed(["for a"]))
    assert cache.get("b", _Feed(["for b"])).value == ["for b"]
    assert cache.get("a", _Feed()).value == ["for a"]


# -------------------------------------------------------------------------
# Failures
# -------------------------------------------------------------------------

def test_a_failed_answer_is_never_stored(clock):
    cache, feed = _cache(), _Feed(DOWN, ["recovered"])
    with pytest.raises(_Down):
        cache.get("k", feed)
    clock.advance(seconds=30)
    assert cache.get("k", feed).value == ["recovered"]
    assert feed.calls == 2


def test_after_a_failure_the_feed_is_not_asked_again_for_a_while(clock):
    """Every caller in the pause is answered at once, not after a timeout."""
    cache, feed = _cache(), _Feed(DOWN, ["recovered"])
    with pytest.raises(_Down):
        cache.get("k", feed)
    clock.advance(seconds=29)
    with pytest.raises(feed_cache.BackingOff):
        cache.get("k", feed)
    assert feed.calls == 1
    clock.advance(seconds=1)
    assert cache.get("k", feed).value == ["recovered"]


def test_the_pause_after_a_failure_is_per_key(clock):
    cache = _cache()
    with pytest.raises(_Down):
        cache.get("a", _Feed(DOWN))
    assert cache.get("b", _Feed(["for b"])).value == ["for b"]


# -------------------------------------------------------------------------
# Older answers standing in
# -------------------------------------------------------------------------

def test_an_older_answer_stands_in_when_the_feed_fails(clock):
    """Marked stale, with the time the feed actually answered."""
    cache, feed = _cache(stale_seconds=3600), _Feed(["floods"], DOWN)
    cache.get("k", feed)
    clock.advance(minutes=20)
    answer = cache.get("k", feed)
    assert (answer.value, answer.fetched_at, answer.stale) == (["floods"], T0, True)


def test_during_the_pause_an_older_answer_stands_in_at_once(clock):
    cache, feed = _cache(stale_seconds=3600), _Feed(["floods"], DOWN)
    cache.get("k", feed)
    clock.advance(minutes=20)
    cache.get("k", feed)
    clock.advance(seconds=10)
    answer = cache.get("k", feed)
    assert answer.stale and answer.value == ["floods"]
    assert feed.calls == 2


def test_an_answer_past_the_stale_limit_does_not_stand_in(clock):
    cache, feed = _cache(stale_seconds=3600), _Feed(["floods"], DOWN)
    cache.get("k", feed)
    clock.advance(seconds=3601)
    with pytest.raises(_Down):
        cache.get("k", feed)


def test_with_no_stale_limit_an_old_answer_never_stands_in(clock):
    """The earthquake setting: an earthquake can happen at any minute."""
    cache, feed = _cache(stale_seconds=0), _Feed(["quakes"], DOWN)
    cache.get("k", feed)
    clock.advance(seconds=61)
    with pytest.raises(_Down):
        cache.get("k", feed)
    with pytest.raises(feed_cache.BackingOff):
        cache.get("k", feed)


def test_an_answer_that_came_back_unreadable_never_lets_an_older_one_stand_in(clock):
    """The feed answered, so it may be saying something new - a flood the
    older answer does not have. Only a feed that could not be reached is
    stood in for."""
    cache, feed = _cache(stale_seconds=3600), _Feed(["floods"], UNREADABLE)
    cache.get("k", feed)
    clock.advance(minutes=20)
    with pytest.raises(ValueError):
        cache.get("k", feed)
    clock.advance(seconds=10)
    with pytest.raises(feed_cache.BackingOff):
        cache.get("k", feed)


def test_an_answer_is_stamped_when_it_arrived(clock):
    def slow():
        clock.advance(seconds=7)
        return ["quakes"]

    assert _cache().get("k", slow).fetched_at == T0 + timedelta(seconds=7)


def test_a_stale_answer_leaves_the_stored_one_unmarked(clock):
    """Once the feed answers again, nothing stale lingers."""
    cache, feed = _cache(stale_seconds=3600), _Feed(["floods"], DOWN, ["new floods"])
    cache.get("k", feed)
    clock.advance(minutes=20)
    assert cache.get("k", feed).stale
    clock.advance(seconds=30)
    answer = cache.get("k", feed)
    assert (answer.value, answer.stale) == (["new floods"], False)


# -------------------------------------------------------------------------
# Clock and memory
# -------------------------------------------------------------------------

def test_when_the_clock_goes_backwards_nothing_cached_is_trusted(clock):
    cache, feed = _cache(stale_seconds=3600), _Feed(["before"], ["after"])
    cache.get("k", feed)
    clock.advance(seconds=-5)
    assert cache.get("k", feed).value == ["after"]


def test_when_the_clock_goes_backwards_an_old_answer_does_not_stand_in(clock):
    cache, feed = _cache(stale_seconds=3600), _Feed(["before"], DOWN)
    cache.get("k", feed)
    clock.advance(seconds=-5)
    with pytest.raises(_Down):
        cache.get("k", feed)


def test_the_least_recently_used_answer_is_dropped_first(clock):
    cache = _cache(max_entries=2)
    cache.get("a", _Feed(["a"]))
    cache.get("b", _Feed(["b"]))
    cache.get("a", _Feed())          # a is now the most recently used
    cache.get("c", _Feed(["c"]))     # so b goes
    refetch_b = _Feed(["b again"])
    assert cache.get("b", refetch_b).value == ["b again"]
    assert refetch_b.calls == 1


def test_clear_all_empties_every_cache(clock):
    cache = _cache()
    cache.get("k", _Feed(["cached"]))
    feed_cache.clear_all()
    refetch = _Feed(["fetched again"])
    assert cache.get("k", refetch).value == ["fetched again"]


# -------------------------------------------------------------------------
# The settings the feeds use
# -------------------------------------------------------------------------

def test_earthquakes_are_cached_for_a_minute_and_never_served_stale():
    assert usgs_earthquakes._ANSWERS.fresh == timedelta(seconds=60)
    assert usgs_earthquakes._ANSWERS.stale <= usgs_earthquakes._ANSWERS.fresh


def test_floods_are_cached_for_15_minutes_and_served_stale_up_to_6_hours():
    assert gdacs_floods._LISTS.fresh == timedelta(minutes=15)
    assert gdacs_floods._LISTS.stale == timedelta(hours=6)
    assert gdacs_floods._AREAS.fresh == timedelta(hours=24)


# -------------------------------------------------------------------------
# No answer outlives its test
# -------------------------------------------------------------------------

def test_every_test_starts_with_every_cache_empty(request):
    """tests/conftest.py empties the caches around every test, whatever order
    the tests run in. This fails if that fixture stops applying to every test."""
    assert "_empty_feed_caches" in request.fixturenames
    assert all(not cache._entries and not cache._failed for cache in feed_cache._CACHES)
