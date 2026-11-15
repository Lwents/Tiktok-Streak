"""Personal TikTok streak sender. Python 3.10+."""
import argparse
import json
import logging
import time
from pathlib import Path
from urllib.parse import urlparse
from profile_lock import BrowserProfileLock

ROOT = Path(__file__).resolve().parent


def read_json(path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding='utf-8'))


def save_state(path, state):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)


def validate(config):
    if not isinstance(config, dict):
        raise ValueError('Cấu hình phải là JSON object.')
    interval = config.get('interval_hours', 20)
    if isinstance(interval, bool) or not isinstance(interval, (float, int)) or not 1 <= interval <= 168:
        raise ValueError('interval_hours phải từ 1 đến 168.')
    if not isinstance(config.get('message'), str) or not config['message'].strip():
        raise ValueError('message không được trống.')
    targets = config.get('conversations', [])
    if not isinstance(targets, list) or not targets:
        raise ValueError('Thêm ít nhất một cuộc trò chuyện vào config.json.')
    seen = set()
    for target in targets:
        url = target.get('url', '')
        parsed = urlparse(url)
        if parsed.scheme != 'https' or parsed.hostname != 'www.tiktok.com' or not parsed.path.startswith('/messages') or parsed.username or parsed.password:
            raise ValueError('URL phải bắt đầu bằng https://www.tiktok.com/messages')
        if parsed.path.rstrip('/') == '/messages' and not parsed.query:
            raise ValueError('Cần URL riêng của cuộc trò chuyện, không dùng URL hộp thư chung.')
        if url in seen:
            raise ValueError('URL cuộc trò chuyện bị trùng.')
        seen.add(url)
    return config


def send(page, target, config, dry_run):
    url = target['url']
    page.goto(url, wait_until='domcontentloaded', timeout=60000)
    editor = page.locator(config.get('editor_selector', '[contenteditable="true"][data-e2e="message-input"]'))
    editor.wait_for(state='visible', timeout=30000)
    if editor.count() != 1:
        raise RuntimeError('Không xác định duy nhất ô nhập tin nhắn.')
    # Never overwrite a draft left by the user.
    existing = editor.inner_text().strip()
    if existing:
        raise RuntimeError('Ô chat có bản nháp; bỏ qua để tránh ghi đè.')
    if dry_run:
        logging.info('[CHẠY THỬ] Tìm thấy ô chat: %s', target.get('name', url))
        return
    editor.fill(config['message'])
    editor.press('Enter')
    try:
        from playwright.sync_api import expect
        expect(editor).to_be_empty(timeout=15000)
    except Exception as exc:
        raise RuntimeError('Chưa xác nhận ô nhập đã trống sau khi gửi; kiểm tra chat trước khi thử lại.') from exc


def main():
    parser = argparse.ArgumentParser(description='Tự gửi tin giữ chuỗi TikTok cho danh sách đã chọn.')
    parser.add_argument('command', choices=['login', 'run', 'once', 'check'])
    parser.add_argument('--dry-run', action='store_true', help='Chỉ kiểm tra ô chat, không gửi tin.')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    if args.command == 'check':
        config = validate(read_json(ROOT / 'config.json', {}))
        print(f"Cấu hình hợp lệ: {len(config['conversations'])} cuộc trò chuyện.")
        return
    config = None if args.command == 'login' else validate(read_json(ROOT / 'config.json', {}))
    from playwright.sync_api import sync_playwright
    lock = BrowserProfileLock(ROOT / '.running.lock')
    lock.acquire()
    try:
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(str(ROOT / 'browser-profile'), headless=False)
            try:
                page = context.pages[0] if context.pages else context.new_page()
                if args.command == 'login':
                    page.goto('https://www.tiktok.com/messages', wait_until='domcontentloaded')
                    input('Đăng nhập trong trình duyệt. Khi xong, nhấn Enter tại đây để lưu phiên... ')
                    return
                state_path = ROOT / 'state.json'
                state = read_json(state_path, {})
                failures = False
                while True:
                    for target in config['conversations']:
                        url = target['url']
                        record = state.get(url, {})
                        # An interrupted/uncertain attempt requires manual review, never automatic retry.
                        if record.get('status') == 'pending':
                            logging.warning('Bỏ qua %s: lần gửi trước chưa rõ kết quả. Kiểm tra chat và state.json.', target.get('name', url))
                            failures = True
                            continue
                        if time.time() - record.get('sent_at', 0) < config.get('interval_hours', 20) * 3600:
                            continue
                        try:
                            if not args.dry_run:
                                state[url] = {'status': 'pending', 'attempt_at': time.time()}
                                save_state(state_path, state)
                            send(page, target, config, args.dry_run)
                            if not args.dry_run:
                                state[url] = {'status': 'sent', 'sent_at': time.time()}
                                save_state(state_path, state)
                                logging.info('Đã thao tác gửi: %s', target.get('name', url))
                        except Exception:
                            failures = True
                            logging.exception('Lỗi với %s', target.get('name', url))
                        if page.is_closed():
                            raise RuntimeError('Trình duyệt đã đóng.')
                        page.wait_for_timeout(3000)
                    if args.command == 'once' or args.dry_run:
                        if failures:
                            raise RuntimeError('Có cuộc trò chuyện lỗi hoặc cần kiểm tra; xem log phía trên.')
                        break
                    page.wait_for_timeout(30000)
            finally:
                context.close()
    finally:
        lock.release()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\nĐã dừng tool.')
    except Exception as error:
        logging.error('%s', error)
        raise SystemExit(1)
