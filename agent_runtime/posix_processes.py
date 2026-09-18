"""Linux process-session ownership for the fixed, non-shell DSH tool chain."""
import os
import signal
import time
from pathlib import Path
from agent_runtime.common import require


def info(pid):
    try:
        tail = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
        return tail[0], int(tail[2]), int(tail[3]), tail[19]
    except (OSError, ValueError, IndexError):
        return None


class PosixJob:
    def __init__(self, pid):
        value = info(pid)
        require(value and value[1] == pid and value[2] == pid, 'job', 'child must own a new Linux session')
        self.pid, self.start = pid, value[3]
        self.name = f'posix:{pid}:{self.start}'
        self.closed = False

    def pids(self):
        if self.closed: return []
        return [int(p.name) for p in Path('/proc').iterdir() if p.name.isdigit()
                and (v := info(int(p.name))) and v[0] != 'Z' and v[1] == self.pid and v[2] == self.pid]

    def close(self):
        if self.closed: return
        leader = info(self.pid)
        require(not leader or leader[3] == self.start, 'job', 'Linux process identity changed')
        if self.pids():
            try: os.killpg(self.pid, signal.SIGKILL)
            except ProcessLookupError: pass
        deadline = time.monotonic() + 10
        while self.pids() and time.monotonic() < deadline: time.sleep(.05)
        require(not self.pids(), 'cancel', 'owned Linux descendants did not exit')
        self.closed = True


def belongs(pid, name):
    prefix, leader, start = name.split(':')
    require(prefix == 'posix', 'job', 'invalid Linux ownership identity')
    parent, child = info(int(leader)), info(pid)
    return bool(parent and parent[3] == start and child and child[1] == int(leader) and child[2] == int(leader))
