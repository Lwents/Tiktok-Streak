"""Open the VPS dashboard through an authenticated SSH tunnel. Stores no password."""
import argparse
import json
import re
import shutil
import subprocess
import time
import webbrowser
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

BASE = 'http://127.0.0.1:8765'
SCREEN = 'http://127.0.0.1:6080/vnc.html?autoconnect=1&resize=scale'
REMOTE = 'root@160.250.180.133'


def current_dashboard():
    try:
        with urlopen(BASE + '/api/state?v=2', timeout=2) as response:
            data = json.load(response)
        if not isinstance(data, dict) or 'status' not in data or 'rows' not in data:
            raise RuntimeError('Cổng 8765 đang được ứng dụng khác dùng.')
        return data
    except URLError:
        return None


def close_local_dashboard():
    data = current_dashboard()
    if data is None:
        return False
    if data.get('runtime', {}).get('mode') == 'vps':
        return True
    if data.get('runtime', {}).get('platform') == 'linux':
        raise RuntimeError('Cổng 8765 đang nối tới một phiên Linux khác. Đóng kết nối cũ rồi thử lại.')
    with urlopen(BASE, timeout=3) as response:
        html = response.read().decode('utf-8')
    token = re.search(r'name="app-token" content="([^"]+)"', html)
    if not token or '<title>Streak' not in html:
        raise RuntimeError('Cổng 8765 đang được ứng dụng khác dùng; không tự đóng ứng dụng đó.')
    request = Request(BASE + '/api/shutdown', data=b'{}', method='POST',
                      headers={'Content-Type': 'application/json', 'Origin': BASE, 'X-App-Token': token[1]})
    with urlopen(request, timeout=5):
        pass
    for _ in range(80):
        if current_dashboard() is None:
            return False
        time.sleep(.1)
    raise RuntimeError('Tool Windows chưa đóng xong. Chờ vài giây rồi mở lại kết nối VPS.')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--browser', action='store_true', help='Mở màn hình Chrome trên VPS.')
    args = parser.parse_args()
    target = SCREEN if args.browser else BASE
    if close_local_dashboard():
        webbrowser.open(target)
        print('Đã mở giao diện VPS qua kết nối SSH đang có.')
        return
    ssh = shutil.which('ssh')
    if not ssh:
        raise RuntimeError('Windows chưa có OpenSSH Client. Cài OpenSSH Client trong Optional Features rồi thử lại.')
    identity = Path.home() / '.ssh' / 'tiktok_streak_160_250_180_133'
    print('Đang kết nối VPS bằng khóa SSH...' if identity.exists() else 'Đang kết nối VPS. Nhập mật khẩu SSH khi được hỏi; mật khẩu không được lưu.', flush=True)
    common = [ssh, '-o', 'StrictHostKeyChecking=accept-new']
    if identity.exists():
        common += ['-i', str(identity), '-o', 'IdentitiesOnly=yes']
    subprocess.run([*common, REMOTE, 'systemctl', 'start', 'tiktok-streak'], check=True)
    command = [*common, '-NT', '-o', 'ExitOnForwardFailure=yes',
               '-o', 'ServerAliveInterval=30', '-o', 'ServerAliveCountMax=3',
               '-L', '127.0.0.1:8765:127.0.0.1:8765', '-L', '127.0.0.1:6080:127.0.0.1:6080', REMOTE]
    tunnel = subprocess.Popen(command)
    try:
        for _ in range(360):
            if tunnel.poll() is not None:
                raise RuntimeError('SSH chưa kết nối được. Xem thông báo phía trên rồi mở lại file này.')
            data = current_dashboard()
            if data and data.get('runtime', {}).get('mode') == 'vps':
                webbrowser.open(target)
                print('Đã kết nối. Đóng cửa sổ này chỉ ngắt giao diện; tool trên VPS vẫn chạy.', flush=True)
                tunnel.wait()
                return
            time.sleep(.5)
        raise RuntimeError('Chưa kết nối được giao diện VPS sau 3 phút.')
    finally:
        if tunnel.poll() is None:
            tunnel.terminate()
            tunnel.wait(timeout=10)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\nĐã đóng kết nối giao diện. Tool trên VPS vẫn chạy.')
    except Exception as exc:
        print('Lỗi:', exc)
        input('Nhấn Enter để đóng... ')
