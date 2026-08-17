import unittest

from desktop.control.domain import ConflictError, ControlLease


class FakeClock:
    def __init__(self):
        self.value = 100.0

    def __call__(self):
        return self.value


class ControlLeaseTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.lease = ControlLease(clock=self.clock, agent_ttl=10, human_ttl=30)

    def test_agent_can_claim_an_unowned_session(self):
        state = self.lease.claim_agent("agent-1")

        self.assertEqual(state["owner"], "agent")
        self.assertEqual(state["ownerId"], "agent-1")

    def test_human_claim_preempts_agent_immediately(self):
        self.lease.claim_agent("agent-1")

        state = self.lease.claim_human("browser-1")

        self.assertEqual(state["owner"], "human")
        with self.assertRaises(ConflictError):
            self.lease.assert_owner("agent", "agent-1")

    def test_agent_cannot_preempt_a_live_human(self):
        self.lease.claim_human("browser-1")

        with self.assertRaises(ConflictError):
            self.lease.claim_agent("agent-1")

    def test_expired_lease_returns_to_observer_mode(self):
        self.lease.claim_agent("agent-1")
        self.clock.value += 11

        self.assertEqual(self.lease.state()["owner"], "none")
        self.lease.claim_agent("agent-2")
        self.assertEqual(self.lease.state()["ownerId"], "agent-2")

    def test_heartbeat_only_renews_the_matching_owner(self):
        self.lease.claim_human("browser-1")

        with self.assertRaises(ConflictError):
            self.lease.heartbeat("human", "browser-2")

        self.clock.value += 20
        renewed = self.lease.heartbeat("human", "browser-1")
        self.assertGreater(renewed["expiresInMs"], 29000)

    def test_extend_if_owner_renews_before_expiry_check(self):
        self.lease.claim_agent("agent-1")
        self.clock.value += 11

        self.lease.extend_if_owner("agent", "agent-1")

        self.assertEqual(self.lease.state()["owner"], "agent")
        self.assertEqual(self.lease.state()["ownerId"], "agent-1")


if __name__ == "__main__":
    unittest.main()
