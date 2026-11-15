"""Minimal Windows UI. All browser work stays on one worker thread."""
import argparse
import queue
import time
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path
from streak import read_json, save_state
from worker import Worker

ROOT = Path(__file__).resolve().parent


class App:
    def __init__(self, root, inspect=False):
        self.root = root
        self.rows = {}
        self.busy = False
        self.events = queue.Queue()
        self.worker = Worker(self.events, inspect)
        self.worker.start()
        root.title('TikTok Streak')
        root.geometry('740x550')
        root.minsize(620, 460)
        frame = ttk.Frame(root, padding=12)
        frame.pack(fill='both', expand=True)
        settings = read_json(ROOT / 'desktop-settings.json', {})
        top = ttk.Frame(frame)
        top.pack(fill='x')
        self.browser_choice = tk.StringVar(value='Edge' if settings.get('channel') == 'msedge' else 'Chrome')
        self.browser_menu = ttk.Combobox(top, textvariable=self.browser_choice, values=('Chrome', 'Edge'), state='readonly', width=9)
        self.browser_menu.pack(side='left', padx=(0, 8))
        self.buttons = []
        for label, command in [('Đăng nhập', 'login'), ('Quét người có lửa', 'scan')]:
            button = ttk.Button(top, text=label, command=lambda c=command: self.submit(c))
            button.pack(side='left', padx=(0, 8))
            self.buttons.append(button)
        ttk.Label(frame, text='Bấm cột Chọn để chọn người nhận. Chỉ gửi khi kiểm tra được huy hiệu chuỗi.').pack(anchor='w', pady=(12, 5))
        table = ttk.Frame(frame)
        table.pack(fill='both', expand=True)
        self.tree = ttk.Treeview(table, columns=('pick', 'name', 'badge'), show='headings', height=9, selectmode='browse')
        for col, title, width in [('pick', 'Chọn', 55), ('name', 'Người nhận', 220), ('badge', 'Dấu hiệu chuỗi', 330)]:
            self.tree.heading(col, text=title)
            self.tree.column(col, width=width, stretch=col != 'pick')
        scrollbar = ttk.Scrollbar(table, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right', fill='y')
        self.tree.pack(side='left', fill='both', expand=True)
        self.tree.bind('<Button-1>', self.toggle)
        options = ttk.Frame(frame)
        options.pack(fill='x', pady=10)
        ttk.Label(options, text='Tin nhắn:').pack(side='left')
        self.message = tk.StringVar(value=settings.get('message', 'Giữ chuỗi nha 🔥'))
        ttk.Entry(options, textvariable=self.message).pack(side='left', fill='x', expand=True, padx=8)
        ttk.Label(options, text='Sau 00:00 mỗi ngày').pack(side='left')
        self.hours = tk.StringVar(value=str(settings.get('hours', 20)))
        actions = ttk.Frame(frame)
        actions.pack(fill='x')
        for label, cmd in [('Gửi một lượt', 'send'), ('Bật tự động', 'auto')]:
            button = ttk.Button(actions, text=label, command=lambda c=cmd: self.submit(c))
            button.pack(side='left', padx=(0, 8))
            self.buttons.append(button)
        ttk.Button(actions, text='Dừng', command=self.stop).pack(side='left')
        self.log = tk.Text(frame, height=7, state='disabled', wrap='word', font=('Segoe UI', 9))
        self.log.pack(fill='x', pady=(10, 0))
        self.write('Bắt đầu: Đăng nhập → Quét người có lửa → Chọn người nhận → Gửi.')
        root.after(100, self.poll)
        root.protocol('WM_DELETE_WINDOW', self.close)

    def write(self, text):
        self.log.configure(state='normal')
        self.log.insert('end', time.strftime('%H:%M:%S ') + text + '\n')
        self.log.see('end')
        self.log.configure(state='disabled')

    def toggle(self, event):
        if self.busy or self.tree.identify_column(event.x) != '#1':
            return
        iid = self.tree.identify_row(event.y)
        if iid:
            self.rows[iid]['selected'] = not self.rows[iid].get('selected', False)
            self.tree.set(iid, 'pick', '✓' if self.rows[iid]['selected'] else '')

    def submit(self, command):
        if self.busy:
            return
        channel = 'msedge' if self.browser_choice.get() == 'Edge' else 'chrome'
        payload = {'channel': channel}
        if command in ('send', 'auto'):
            targets = [r for r in self.rows.values() if r.get('selected')]
            try:
                hours = float(self.hours.get())
                if not 1 <= hours <= 168 or not self.message.get().strip() or not targets:
                    raise ValueError()
            except ValueError:
                messagebox.showinfo('Thiếu thông tin', 'Chọn người nhận và nhập tin nhắn.')
                return
            payload.update(targets=targets, message=self.message.get().strip(), hours=hours)
            self.worker.stop_sending.clear()
        elif command == 'scan':
            self.stop()
        elif command == 'login':
            self.stop()
        save_state(ROOT / 'desktop-settings.json', {'message': self.message.get(), 'hours': self.hours.get(), 'channel': channel})
        self.busy = True
        self.browser_menu.configure(state='disabled')
        for button in self.buttons:
            button.configure(state='disabled')
        self.worker.commands.put((command, payload))
        self.write({'login': 'Đang mở trình duyệt...', 'scan': 'Đang quét danh sách chat...', 'send': 'Đang kiểm tra và gửi...', 'auto': 'Đang bật tự động...'}[command])

    def stop(self):
        self.worker.stop_sending.set()
        self.worker.commands.put(('stop', None))
        self.write('Đã yêu cầu dừng. Thao tác trình duyệt đang thực hiện sẽ kết thúc trước.')

    def poll(self):
        while True:
            try:
                kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == 'log':
                self.write(value)
            elif kind == 'ready':
                self.busy = False
                self.browser_menu.configure(state='readonly')
                for button in self.buttons:
                    button.configure(state='normal')
            elif kind == 'rows':
                self.tree.delete(*self.tree.get_children())
                self.rows.clear()
                for i, row in enumerate(value):
                    iid = str(i)
                    self.rows[iid] = row
                    self.tree.insert('', 'end', iid=iid, values=('', row['name'], row['badge']))
        self.root.after(100, self.poll)

    def close(self):
        self.worker.stop_sending.set()
        self.worker.closing.set()
        for button in self.buttons:
            button.configure(state='disabled')
        self.write('Đang đóng trình duyệt...')
        self.wait_close()

    def wait_close(self):
        if self.worker.is_alive():
            self.root.after(200, self.wait_close)
        else:
            self.root.destroy()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--inspect', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--login', action='store_true', help='Mở trang đăng nhập khi khởi động')
    args = parser.parse_args()
    app_root = tk.Tk()
    ttk.Style().theme_use('clam')
    app = App(app_root, args.inspect)
    if args.login:
        app_root.after(300, lambda: app.submit('login'))
    app_root.mainloop()
