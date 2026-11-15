"""Regression coverage for installed Windows browsers and closed-session recovery."""
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tiktok_browser import TikTokBrowser


@unittest.skipUnless(sys.platform == 'win32', 'Installed Windows browsers required')
class LifecycleChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.adapter = TikTokBrowser(Path(self.tmp.name))

    def tearDown(self):
        self.adapter.close()
        self.tmp.cleanup()

    def test_reopen_chrome_after_last_window_closed(self):
        self.assertTrue(self.adapter.ensure_open('chrome'))
        self.adapter.page.set_content('<title>First window</title>')
        original = self.adapter.context
        self.adapter.page.close()
        self.assertFalse(self.adapter.pump())
        self.assertTrue(self.adapter.ensure_open('chrome'))
        self.assertIsNot(self.adapter.context, original)
        self.adapter.page.set_content('<title>Recovered window</title>')
        self.assertEqual(self.adapter.page.title(), 'Recovered window')
        self.assertFalse(self.adapter.ensure_open('chrome'))

    def test_switch_to_installed_edge(self):
        self.adapter.ensure_open('chrome')
        self.assertTrue(self.adapter.ensure_open('msedge'))
        self.assertEqual(self.adapter.channel, 'msedge')
        self.adapter.page.set_content('<title>Edge works</title>')
        self.assertEqual(self.adapter.page.title(), 'Edge works')
        self.assertTrue(self.adapter.pump())

    def test_retry_after_launch_failure(self):
        with patch('playwright.sync_api.BrowserType.launch_persistent_context', side_effect=RuntimeError('simulated launch failure')):
            with self.assertRaisesRegex(RuntimeError, 'Không mở được Chrome'):
                self.adapter.open('chrome')
        self.assertIsNone(self.adapter.context)
        self.assertIsNone(self.adapter.playwright)
        self.assertTrue(self.adapter.ensure_open('chrome'))
        self.assertTrue(self.adapter.pump())

    def test_persistent_session_cookie_survives_browser_restart(self):
        self.adapter.ensure_open('chrome')
        self.adapter.context.add_cookies([{'name': 'test_session', 'value': 'fixture-only',
                                          'domain': 'example.test', 'path': '/',
                                          'expires': time.time() + 86400, 'httpOnly': True,
                                          'secure': True, 'sameSite': 'Lax'}])
        self.adapter.close()
        self.adapter.ensure_open('chrome')
        cookies = self.adapter.context.cookies('https://example.test/')
        self.assertEqual([(c['name'], c['value']) for c in cookies], [('test_session', 'fixture-only')])


if __name__ == '__main__':
    unittest.main()
