"""Separate a page still loading from a confirmed account change/logout."""
import time


class AccountState:
    def __init__(self, logout_grace=6):
        self.logout_grace = logout_grace
        self.account = None
        self.checking = False
        self.logout_since = None
        self.logout_samples = 0

    def observe(self, current, now=None):
        now = time.monotonic() if now is None else now
        if current is None or (current.get('authenticated') and not current.get('username')):
            self.checking = True
            self.logout_since = None
            self.logout_samples = 0
            return self.account
        if not current.get('authenticated') and (self.account or {}).get('authenticated'):
            if self.logout_since is None:
                self.logout_since = now
            self.logout_samples += 1
            if self.logout_samples < 2 or now - self.logout_since < self.logout_grace:
                self.checking = True
                return self.account
        self.account = current
        self.checking = False
        self.logout_since = None
        self.logout_samples = 0
        return self.account
