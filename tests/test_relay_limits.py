from localagent.relay.limits import RateLimiter


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_limiter_allows_n_per_minute_then_refuses_then_recovers():
    clock = Clock()
    limiter = RateLimiter(30, clock=clock)
    assert all(limiter.allow("1.2.3.4") for _ in range(30))
    assert not limiter.allow("1.2.3.4")
    assert limiter.allow("5.6.7.8")  # per key
    clock.now += 60
    assert limiter.allow("1.2.3.4")


def test_limiter_forgets_idle_keys():
    clock = Clock()
    limiter = RateLimiter(5, clock=clock)
    for i in range(100):
        limiter.allow(f"10.0.0.{i}")
    clock.now += 61
    limiter.allow("1.1.1.1")
    assert len(limiter) == 1
