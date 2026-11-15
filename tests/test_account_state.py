import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from account_state import AccountState


class AccountStateChecks(unittest.TestCase):
    def setUp(self):
        self.state = AccountState()
        self.owner = {'authenticated': True, 'username': 'owner'}
        self.state.observe(self.owner, now=0)

    def test_missing_navigation_during_reload_keeps_account(self):
        self.assertEqual(self.state.observe(None, now=3), self.owner)
        self.assertTrue(self.state.checking)
        self.assertEqual(self.state.observe(self.owner, now=4), self.owner)
        self.assertFalse(self.state.checking)

    def test_short_login_button_flash_does_not_log_out(self):
        self.assertEqual(self.state.observe({'authenticated': False}, now=3), self.owner)
        self.assertEqual(self.state.observe({'authenticated': False}, now=6), self.owner)
        self.assertEqual(self.state.observe(self.owner, now=7), self.owner)
        self.assertFalse(self.state.checking)

    def test_persistent_explicit_logout_is_confirmed(self):
        self.state.observe({'authenticated': False}, now=3)
        self.state.observe({'authenticated': False}, now=6)
        self.assertFalse(self.state.observe({'authenticated': False}, now=9)['authenticated'])

    def test_real_authenticated_switch_is_immediate(self):
        other = {'authenticated': True, 'username': 'other'}
        self.assertEqual(self.state.observe(other, now=1), other)
        self.assertFalse(self.state.checking)

    def test_unknown_page_interrupts_logout_confirmation(self):
        self.state.observe({'authenticated': False}, now=3)
        self.state.observe(None, now=6)
        self.assertEqual(self.state.observe({'authenticated': False}, now=9), self.owner)
