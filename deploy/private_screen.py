"""Serve loopback noVNC to SSH clients and the configured authenticated HTTPS proxy."""
from websockify.websocketproxy import ProxyRequestHandler, WebSocketProxy
import os
from urllib.parse import urlparse

public_origin = os.environ.get('TIKTOK_PUBLIC_ORIGIN', '').rstrip('/')
public_host = ''
if public_origin:
    parsed = urlparse(public_origin)
    if parsed.scheme != 'https' or not parsed.netloc or parsed.path or parsed.username or parsed.password:
        raise SystemExit('Invalid browser-screen public origin')
    public_host = parsed.netloc


class PrivateScreen(ProxyRequestHandler):
    hosts = {'127.0.0.1:6080', 'localhost:6080'}
    origins = {'http://' + host for host in hosts}
    if public_origin:
        hosts = hosts | {public_host}
        origins = origins | {public_origin}

    def handle_upgrade(self):
        if self.headers.get('Host') not in self.hosts or self.headers.get('Origin') not in self.origins:
            self.send_error(403, 'Open the browser screen from the configured tool address.')
            return
        super().handle_upgrade()

    def do_GET(self):
        if self.headers.get('Host') not in self.hosts:
            self.send_error(403)
            return
        super().do_GET()


if __name__ == '__main__':
    WebSocketProxy(RequestHandlerClass=PrivateScreen, listen_host='127.0.0.1', listen_port=6080,
                   target_host='127.0.0.1', target_port=5900, web='/usr/share/novnc').start_server()
