import unittest

from desktop.control.metrics import MetricsRegistry


class MetricsRegistryTests(unittest.TestCase):
    def test_prometheus_output_includes_counters(self):
        metrics = MetricsRegistry()
        metrics.inc("relay_input_batches_total", 2)
        output = metrics.prometheus()
        self.assertIn("relay_input_batches_total 2", output)
        self.assertIn("# TYPE relay_input_batches_total counter", output)


if __name__ == "__main__":
    unittest.main()
