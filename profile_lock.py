"""OS-held browser ownership; a crash releases the lock without deleting a marker."""
import json
import os
import time


class BrowserProfileLock:
    def __init__(self, path):
        self.path = path
        self.file = None

    def acquire(self, timeout=0, cancel=None):
        if self.file is not None:
            return
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        handle = os.fdopen(fd, 'r+b', buffering=0)
        # Windows byte-range locks require a stable byte. Never unlink this file:
        # replacing it could let two processes lock different files at this path.
        if os.fstat(fd).st_size == 0:
            handle.write(b' ')
        deadline = time.monotonic() + timeout
        try:
            while True:
                if cancel is not None and cancel.is_set():
                    raise RuntimeError('Đã dừng mở trình duyệt.')
                handle.seek(0)
                try:
                    if os.name == 'nt':
                        import msvcrt
                        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise RuntimeError('Một cửa sổ tool khác đang giữ trình duyệt. Đóng cửa sổ đó rồi thử lại.') from None
                    if cancel is not None:
                        cancel.wait(min(.1, remaining))
                    else:
                        time.sleep(min(.1, remaining))
            handle.seek(0)
            handle.write((json.dumps({'pid': os.getpid()}) + '\n').encode('ascii'))
            handle.truncate()
            self.file = handle
        except BaseException:
            handle.close()
            raise

    def release(self):
        if self.file is not None:
            # Closing the descriptor releases both Windows and POSIX locks.
            self.file.close()
            self.file = None
