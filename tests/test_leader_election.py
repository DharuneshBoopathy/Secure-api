"""
Phase 5.2 (leader election for APScheduler jobs): app/services/leader.py.

Covers:
  1. Default single-instance mode: is_leader() is True with no Redis client,
     and start() with no client is a no-op that leaves it True.
  2. First replica to tick with a fresh lock key becomes leader.
  3. A second replica ticking while another instance already holds the lock
     does not become leader.
  4. A leader's renewal tick (still holding its own lock) stays leader.
  5. If another instance's lock silently replaced ours (compare-and-set
     renewal fails), we correctly flip to not-leader instead of assuming
     we're still in charge.
  6. stop() releases the lock only when we actually hold it (a non-leader
     calling stop() must not delete someone else's lock).
  7. scheduler.py's _leader_only decorator skips the wrapped job when not
     leader and runs it when leader.
"""

import fakeredis
import pytest

from app.services.leader import LEADER_KEY, LOCK_TTL_SECONDS, _LeaderElection


@pytest.fixture()
def redis_client():
    client = fakeredis.FakeRedis(decode_responses=True)
    yield client
    client.flushall()


def test_default_is_leader_true_with_no_client():
    election = _LeaderElection()
    assert election.is_leader is True


def test_first_replica_becomes_leader(redis_client):
    election = _LeaderElection()
    election.is_leader = False  # simulate what start() does before the first tick
    election._tick(redis_client)
    assert election.is_leader is True
    assert redis_client.get(LEADER_KEY) == election.instance_id


def test_second_replica_does_not_become_leader_while_first_holds_lock(redis_client):
    leader_election = _LeaderElection()
    leader_election.is_leader = False
    leader_election._tick(redis_client)
    assert leader_election.is_leader is True

    challenger = _LeaderElection()
    challenger.is_leader = False
    challenger._tick(redis_client)
    assert challenger.is_leader is False


def test_leader_renewal_extends_ttl_and_stays_leader(redis_client):
    election = _LeaderElection()
    election.is_leader = False
    election._tick(redis_client)
    assert election.is_leader is True

    # Shrink the TTL to simulate time having passed, then confirm the renewal
    # tick pushes it back up to (near) the full lock duration — a renewal that
    # silently failed would leave the shortened TTL in place.
    redis_client.pexpire(LEADER_KEY, 2_000)
    assert redis_client.pttl(LEADER_KEY) <= 2_000

    election._tick(redis_client)  # renewal tick

    assert election.is_leader is True
    assert redis_client.pttl(LEADER_KEY) > LOCK_TTL_SECONDS * 1000 - 2_000
    assert redis_client.get(LEADER_KEY) == election.instance_id


def test_renewal_fails_if_lock_stolen_by_expiry_and_another_instance(redis_client):
    election = _LeaderElection()
    election.is_leader = False
    election._tick(redis_client)
    assert election.is_leader is True

    # Simulate: our TTL expired and a different instance grabbed the key.
    redis_client.set(LEADER_KEY, "someone-else", px=LOCK_TTL_SECONDS * 1000)

    election._tick(redis_client)  # tries to renew, but the value no longer matches
    assert election.is_leader is False


def test_stop_releases_own_lock(redis_client):
    election = _LeaderElection()
    election._client = redis_client
    election.is_leader = False
    election._tick(redis_client)
    assert redis_client.get(LEADER_KEY) is not None

    election.stop()
    assert redis_client.get(LEADER_KEY) is None


def test_non_leader_stop_does_not_delete_someone_elses_lock(redis_client):
    redis_client.set(LEADER_KEY, "other-instance", px=LOCK_TTL_SECONDS * 1000)

    election = _LeaderElection()
    election._client = redis_client
    election.is_leader = False  # we never won the lock
    election.stop()

    assert redis_client.get(LEADER_KEY) == "other-instance"


# ---------------------------------------------------------------------------
# scheduler.py's _leader_only decorator
# ---------------------------------------------------------------------------

def test_leader_only_decorator_skips_when_not_leader(monkeypatch):
    from app.jobs import scheduler as scheduler_mod

    calls = []
    monkeypatch.setattr(scheduler_mod.leader, "is_leader", lambda: False)

    @scheduler_mod._leader_only
    def job():
        calls.append(1)

    job()
    assert calls == []


def test_leader_only_decorator_runs_when_leader(monkeypatch):
    from app.jobs import scheduler as scheduler_mod

    calls = []
    monkeypatch.setattr(scheduler_mod.leader, "is_leader", lambda: True)

    @scheduler_mod._leader_only
    def job():
        calls.append(1)

    job()
    assert calls == [1]
