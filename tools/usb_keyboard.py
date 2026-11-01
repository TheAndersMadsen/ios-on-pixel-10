"""Nonblocking host keyboard with terminal settings restored on exit."""
import os
import select
import sys
import termios
import tty


class Keyboard:
    def __init__(self):
        self.fd = None
        self.saved = None

    def __enter__(self):
        return self

    def enable(self):
        self.fd = sys.stdin.fileno()
        if os.isatty(self.fd):
            self.saved = termios.tcgetattr(self.fd)
            tty.setcbreak(self.fd)

    def poll(self):
        if self.fd is None or not select.select([self.fd], [], [], 0)[0]:
            return None
        return os.read(self.fd, 64)

    def __exit__(self, *exc):
        if self.saved is not None:
            termios.tcsetattr(self.fd, termios.TCSANOW, self.saved)
