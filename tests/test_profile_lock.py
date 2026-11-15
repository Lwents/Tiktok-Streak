"""Browser ownership survives restarts without allowing concurrent owners."""
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from profile_lock import BrowserProfileLock


class ProfileLockChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / '.running.lock'
        self.locks = []

    def tearDown(self):
        for lock in self.locks:
            lock.release()
        self.tmp.cleanup()

    def make_lock(self):
        lock = BrowserProfileLock(self.path)
        self.locks.append(lock)
        return lock

    def test_stale_empty_marker_does_not_block(self):
        self.path.touch()
        self.make_lock().acquire()

    def test_live_owner_blocks_second_owner_and_release_allows_retry(self):
        owner, other = self.make_lock(), self.make_lock()
        owner.acquire()
        with self.assertRaisesRegex(RuntimeError, 'khác đang giữ'):
            other.acquire()
        owner.release()
        other.acquire()

    def test_cancelled_wait_does_not_steal_lock(self):
        self.make_lock().acquire()
        cancelled = threading.Event()
        cancelled.set()
        with self.assertRaisesRegex(RuntimeError, 'Đã dừng'):
            self.make_lock().acquire(timeout=10, cancel=cancelled)

    def test_killed_process_releases_ownership_automatically(self):
        code = ('import sys; from pathlib import Path; from profile_lock import BrowserProfileLock; '
                'lock=BrowserProfileLock(Path(sys.argv[1])); lock.acquire(); '
                'print("locked",flush=True); sys.stdin.read()')
        child = subprocess.Popen([sys.executable, '-c', code, str(self.path)],
                                 cwd=Path(__file__).resolve().parents[1],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 text=True)
        try:
            self.assertEqual(child.stdout.readline().strip(), 'locked')
            other = self.make_lock()
            with self.assertRaises(RuntimeError):
                other.acquire()
            child.kill()
            child.wait(timeout=5)
            self.assertTrue(self.path.exists())
            other.acquire()
        finally:
            if child.poll() is None:
                child.kill()
            child.communicate(timeout=5)
