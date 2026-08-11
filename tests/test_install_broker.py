import tempfile
import unittest
from pathlib import Path

from desktop.broker.install_broker import (
    ApprovalError,
    ApprovalStore,
    InstallBrokerCore,
    ValidationError,
)


class FakeClock:
    def __init__(self):
        self.value = 100.0

    def __call__(self):
        return self.value


class RecordingInstaller:
    def __init__(self):
        self.plans = []

    def install(self, plan):
        self.plans.append(plan)
        return {"installed": plan}


class InstallBrokerTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.approvals = ApprovalStore(clock=self.clock, ttl=120)
        self.installer = RecordingInstaller()
        self.broker = InstallBrokerCore(self.approvals, self.installer)

    def test_exact_approval_is_single_use(self):
        plan = {"kind": "apt", "packages": ["firefox-esr", "jq"]}
        approval = self.broker.approve(plan)

        result = self.broker.install(approval["approvalId"], plan)

        self.assertEqual(result["installed"]["packages"], ["firefox-esr", "jq"])
        with self.assertRaises(ApprovalError):
            self.broker.install(approval["approvalId"], plan)

    def test_approval_cannot_authorize_a_different_package(self):
        approved = {"kind": "apt", "packages": ["jq"]}
        approval = self.broker.approve(approved)

        with self.assertRaises(ApprovalError):
            self.broker.install(
                approval["approvalId"], {"kind": "apt", "packages": ["curl"]}
            )

    def test_approval_expires(self):
        plan = {"kind": "apt", "packages": ["jq"]}
        approval = self.broker.approve(plan)
        self.clock.value += 121

        with self.assertRaises(ApprovalError):
            self.broker.install(approval["approvalId"], plan)

    def test_rejects_option_like_or_malformed_package_names(self):
        for package in ("--allow-unauthenticated", "bad package", "../curl", ""):
            with self.subTest(package=package), self.assertRaises(ValidationError):
                self.broker.approve({"kind": "apt", "packages": [package]})

    def test_deb_must_be_a_regular_file_below_downloads(self):
        with tempfile.TemporaryDirectory() as directory:
            downloads = Path(directory) / "Downloads"
            downloads.mkdir()
            package = downloads / "demo.deb"
            package.write_bytes(b"not a real deb; validation here is path-only")
            self.broker.downloads = downloads

            accepted = self.broker.approve({"kind": "deb", "path": str(package)})
            self.assertIn("approvalId", accepted)

            with self.assertRaises(ValidationError):
                self.broker.approve({"kind": "deb", "path": "/tmp/escape.deb"})

    def test_deb_replacement_invalidates_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            downloads = Path(directory) / "Downloads"
            downloads.mkdir()
            package = downloads / "demo.deb"
            package.write_bytes(b"approved bytes")
            self.broker.downloads = downloads
            approval = self.broker.approve({"kind": "deb", "path": str(package)})

            package.write_bytes(b"replacement bytes")

            with self.assertRaises(ApprovalError):
                self.broker.install(
                    approval["approvalId"], {"kind": "deb", "path": str(package)}
                )


if __name__ == "__main__":
    unittest.main()
