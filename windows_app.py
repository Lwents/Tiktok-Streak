"""Open the local dashboard in a standalone Windows WebView2 window."""

import ctypes
import logging
import threading

from web_app import Dashboard, ROOT, WebServer

TITLE = 'TikTok Streak'
PORT = 8765


def run():
    import webview

    # Claim the local dashboard port before starting the worker. A second
    # launch must not open another Chrome session or run another sender.
    try:
        server = WebServer(('127.0.0.1', PORT), None)
    except OSError as error:
        raise RuntimeError('Cổng 8765 đang được sử dụng. Hãy đóng phiên TikTok Streak đang mở rồi thử lại.') from error

    with server:
        app = Dashboard(desktop_window=True)
        server.app = app
        try:
            window = webview.create_window(
                TITLE, f'http://127.0.0.1:{server.server_port}',
                width=1320, height=900, min_size=(720, 540),
            )
            server_thread = threading.Thread(target=server.serve_forever, daemon=True)

            def close_window_on_shutdown():
                server_thread.join()
                if not window.events.closed.is_set():
                    window.destroy()

            server_thread.start()
            try:
                webview.start(close_window_on_shutdown, gui='edgechromium',
                              private_mode=False, storage_path=str(ROOT / 'desktop-webview'))
            finally:
                app.worker.stop_sending.set()
                app.worker.closing.set()
                server.shutdown()
                server_thread.join()
        finally:
            app.close()


if __name__ == '__main__':
    try:
        run()
    except Exception as error:
        logging.basicConfig(filename=ROOT / 'windows-app.log', encoding='utf-8')
        logging.exception('Không mở được app Windows')
        message = str(error) if isinstance(error, RuntimeError) else (
            'Không mở được TikTok Streak. Hãy chạy setup.bat và kiểm tra Microsoft Edge WebView2 Runtime.'
        )
        ctypes.windll.user32.MessageBoxW(None, message, TITLE, 0x10)
