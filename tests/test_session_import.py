import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from session_import import apply_session_import
from tiktok_browser import TikTokBrowser


class SessionImportChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.path = self.root / 'session-import.json'
        self.cookie = {'name': 'sessionid', 'value': 'fixture-only', 'domain': '.tiktok.com',
                       'path': '/', 'httpOnly': True, 'secure': True, 'sameSite': 'Lax'}

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, username='owner', cookies=None):
        self.path.write_text(json.dumps({'account_username': username, 'cookies': cookies or [self.cookie]}))

    def test_only_tiktok_cookies_are_imported_and_file_waits_for_verification(self):
        self.write(cookies=[self.cookie, {**self.cookie, 'domain': '.unrelated.test'}])
        context = Mock()
        self.assertEqual(apply_session_import(context, self.path), 'owner')
        context.add_cookies.assert_called_once_with([self.cookie])
        self.assertTrue(self.path.exists())

    def test_private_import_is_removed_only_after_expected_account_is_confirmed(self):
        self.write()
        adapter = TikTokBrowser(self.root)
        adapter.page = Mock()
        adapter.page.is_closed.return_value = False
        adapter.page.url = 'https://www.tiktok.com/messages'
        adapter.imported_username = 'owner'
        adapter.page.evaluate.return_value = None
        self.assertIsNone(adapter.read_account())
        self.assertTrue(self.path.exists())
        adapter.page.evaluate.return_value = {'authenticated': True, 'username': 'owner'}
        self.assertEqual(adapter.read_account()['username'], 'owner')
        self.assertFalse(self.path.exists())

    def test_different_account_does_not_consume_import(self):
        self.write()
        adapter = TikTokBrowser(self.root)
        adapter.page = Mock()
        adapter.page.is_closed.return_value = False
        adapter.page.url = 'https://www.tiktok.com/messages'
        adapter.imported_username = 'owner'
        adapter.page.evaluate.return_value = {'authenticated': True, 'username': 'other'}
        with self.assertRaisesRegex(RuntimeError, 'không khớp'):
            adapter.read_account()
        self.assertTrue(self.path.exists())

    def test_missing_import_does_not_change_context(self):
        context = Mock()
        self.assertIsNone(apply_session_import(context, self.path))
        context.add_cookies.assert_not_called()
