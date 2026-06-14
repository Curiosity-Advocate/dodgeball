import time

from app.auth.ratelimit import RateLimiter


def test_allows_up_to_max_then_blocks():
    rl = RateLimiter(max_attempts=3, window_seconds=60)
    assert [rl.allow("k") for _ in range(4)] == [True, True, True, False]


def test_keys_are_independent():
    rl = RateLimiter(1, 60)
    assert rl.allow("a")
    assert rl.allow("b")  # different key, unaffected
    assert not rl.allow("a")


def test_recovers_after_window():
    rl = RateLimiter(1, window_seconds=0.05)
    assert rl.allow("k")
    assert not rl.allow("k")
    time.sleep(0.06)  # window slides past the first attempt
    assert rl.allow("k")
