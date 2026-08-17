import unittest

from desktop.control.events import EventLog


class EventLogTests(unittest.TestCase):
    def test_emit_and_list_returns_recent_entries(self):
        log = EventLog(capacity=3)
        log.emit("control.claimed", "Agent claimed control", {"ownerId": "agent-1"})
        log.emit("control.released", "Agent released control", {"ownerId": "agent-1"})

        events = log.list(10)

        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["kind"], "control.claimed")
        self.assertEqual(events[1]["title"], "Agent released control")
        self.assertIn("createdAtMs", events[0])
        self.assertGreaterEqual(log.uptime_ms(), 0)

    def test_ring_buffer_drops_oldest_entries(self):
        log = EventLog(capacity=2)
        log.emit("one", "first")
        log.emit("two", "second")
        log.emit("three", "third")

        events = log.list(10)

        self.assertEqual([event["title"] for event in events], ["second", "third"])


if __name__ == "__main__":
    unittest.main()
