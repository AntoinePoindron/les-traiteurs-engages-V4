"""Lock the timing-safe login behaviour (audit VULN-102).

The /login response time MUST be (approximately) the same whether the
email exists in the DB or not. Otherwise an attacker can enumerate
registered emails by measuring response latency, even though the error
message is uniform.

We measure the median over a few samples to absorb GC / scheduler noise,
and assert the delta stays under a generous threshold. bcrypt at cost 12
takes ~250 ms; a leak would be >100 ms; we set the bar at 100 ms which
is comfortable for the test environment but still catches a regression.
"""

import time
import pytest


@pytest.mark.timing
def test_login_response_time_is_constant_for_unknown_email(client, login):
    """A POST /login with an unknown email must take roughly as long as
    one with a known email, so an attacker cannot enumerate accounts."""

    def _measure(email: str, samples: int = 5) -> float:
        ts = []
        for _ in range(samples):
            t0 = time.perf_counter()
            client.post("/login", data={"email": email, "password": "x" * 16})
            ts.append(time.perf_counter() - t0)
        ts.sort()
        # Drop best and worst to denoise — keep the middle 3.
        return sum(ts[1:-1]) / len(ts[1:-1])

    known = _measure("alice@test.local")
    unknown = _measure("nope_8a3f@example.invalid")

    delta = abs(known - unknown)
    assert delta < 0.10, (
        f"Login timing leak detected: {delta * 1000:.1f} ms between "
        f"known ({known * 1000:.0f} ms) and unknown ({unknown * 1000:.0f} ms) "
        "emails. An attacker can enumerate accounts via response timing."
    )
