import unittest

from desktop.control.auth import secrets_match


class SecretMatchTests(unittest.TestCase):
    def test_accepts_equal_secrets(self):
        self.assertTrue(secrets_match("token-value", "token-value"))

    def test_rejects_different_lengths_without_raising(self):
        self.assertFalse(secrets_match("short", "much-longer-secret"))
        self.assertFalse(secrets_match("", "token-value"))
        self.assertFalse(secrets_match(None, "token-value"))
        self.assertFalse(secrets_match("token-value", "token-valuf"))
