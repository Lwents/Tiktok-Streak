import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from connect_vps import close_local_dashboard, BASE


class VPSConnectorChecks(unittest.TestCase):
    def test_existing_vps_tunnel_is_reused_without_stopping_remote_worker(self):
        with patch('connect_vps.current_dashboard',return_value={'runtime':{'platform':'linux','mode':'vps'}}), patch('connect_vps.urlopen') as request:
            self.assertTrue(close_local_dashboard())
            request.assert_not_called()

    def test_old_windows_dashboard_is_closed_with_its_own_token(self):
        html=Mock();html.__enter__=Mock(return_value=html);html.__exit__=Mock(return_value=False)
        html.read.return_value=b'<title>Streak</title><meta name="app-token" content="fixture-token">'
        response=Mock();response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
        with patch('connect_vps.current_dashboard',side_effect=[{'runtime':{'platform':'win32'}},None]), patch('connect_vps.urlopen',side_effect=[html,response]) as request:
            self.assertFalse(close_local_dashboard())
            post=request.call_args.args[0]
            self.assertEqual(post.full_url,BASE+'/api/shutdown')
            self.assertEqual(post.get_header('X-app-token'),'fixture-token')

    def test_unrelated_server_is_never_shut_down(self):
        response=Mock();response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
        response.read.return_value=b'<title>Another application</title>'
        with patch('connect_vps.current_dashboard',return_value={'runtime':{}}), patch('connect_vps.urlopen',return_value=response) as request:
            with self.assertRaisesRegex(RuntimeError,'ứng dụng khác'):
                close_local_dashboard()
            self.assertEqual(request.call_count,1)
