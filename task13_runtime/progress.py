"""Small structured execution signals, without prompts, arguments, replies or paths."""
import hashlib
import json
import time
from task13_runtime.common import TOOLS, append

CODES = {'model_started', 'model_finished', 'tool_started', 'tool_finished', 'tool_failed', 'checking', 'preparing'}


def signal(directory, turn_id, code, operation='', tool=''):
    event = {'turn_id': turn_id, 'code': code, 'operation': hashlib.sha256(str(operation).encode()).hexdigest()[:24] if operation else '',
             'tool': tool, 'at': time.time()}
    append(directory / 'execution.jsonl', event)


class ProgressReader:
    def __init__(self, directory, turn_id, callback):
        self.path, self.turn_id, self.callback = directory / 'execution.jsonl', turn_id, callback
        self.offset = 0

    def drain(self):
        if self.callback is None or not self.path.exists(): return
        with self.path.open('rb') as stream:
            stream.seek(self.offset)
            while True:
                line = stream.readline()
                if not line.endswith(b'\n'): break  # partial append is retried next time
                self.offset = stream.tell()
                if len(line) > 4096: continue
                try: event = json.loads(line)
                except (ValueError, UnicodeError): continue
                if event.get('turn_id') != self.turn_id or event.get('code') not in CODES: continue
                if event.get('code', '').startswith('tool_') and event.get('tool') not in TOOLS: continue
                self.callback(event)
