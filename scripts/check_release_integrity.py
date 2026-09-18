"""Offline regression for reserialized deployment JSON and byte-pinned application files."""
import copy
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agent_runtime.common import HostError
from product_core import release
from product_core.paths import STATE


def main():
    installed = release.verify(False)
    checks = []
    STATE.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='release-integrity-', dir=STATE) as directory:
        root = Path(directory)
        for name in [*installed['source_files'], 'product_release.json']:
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)
        config_file = root / 'vercel.json'
        original = config_file.read_bytes()
        config = json.loads(original)

        def check(label, data, accepted):
            config_file.write_bytes(data)
            try:
                release.verify(False)
            except HostError:
                if accepted:
                    raise
            else:
                if not accepted:
                    raise AssertionError('Unexpectedly accepted: ' + label)
            checks.append(label)

        def changed(label, edit):
            candidate = copy.deepcopy(config)
            edit(candidate)
            check(label, json.dumps(candidate).encode(), False)

        with patch.object(release, 'ROOT', root):
            check('original bytes', original, True)
            check('compact JSON', json.dumps(config, separators=(',', ':')).encode(), True)
            check('CRLF and indentation', (json.dumps(config, indent=4) + '\n').replace('\n', '\r\n').encode(), True)
            check('object key order', json.dumps(dict(reversed(list(config.items())))).encode(), True)
            changed('changed API route rejected', lambda c: c['rewrites'][0].update(destination='/other'))
            changed('reordered routes rejected', lambda c: c['rewrites'].reverse())
            changed('removed security headers rejected', lambda c: c.pop('headers'))
            changed('changed duration rejected', lambda c: c['functions']['api/index.py'].update(maxDuration=900))
            changed('extra config field rejected', lambda c: c.update(cleanUrls=True))
            changed('type change rejected', lambda c: c['functions']['api/index.py'].update(maxDuration='300'))
            check('malformed JSON rejected', b'{', False)
            check('duplicate keys rejected', original.rstrip()[:-1] + b',"framework":null}', False)
            check('nested duplicate keys rejected', original.replace(b'"maxDuration": 300', b'"maxDuration": 300, "maxDuration": 300'), False)
            check('non-finite number rejected', original.replace(b'"maxDuration": 300', b'"maxDuration": NaN'), False)
            config_file.unlink()
            try:
                release.verify(False)
            except HostError:
                checks.append('missing config rejected')
            else:
                raise AssertionError('Missing config passed')
            config_file.write_bytes(original)

            other = root / 'requirements.txt'
            other.write_bytes(other.read_bytes() + b'\n')
            try:
                release.verify(False)
            except HostError:
                checks.append('other source remains byte-pinned')
            else:
                raise AssertionError('Changed application source passed')
            shutil.copyfile(ROOT / 'requirements.txt', other)

            asset = root / 'model.json'
            data = b'{"model": 1}'
            entry = {'size': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
                     'json_sha256': release.json_sha(data)}
            asset.write_bytes(b'{"model":1}')
            try:
                release.check_file(root, 'model.json', entry)
            except HostError:
                checks.append('JSON exception cannot apply to another file')
            else:
                raise AssertionError('Changed asset bytes passed')

            (root / 'product_release.json').write_bytes(b'{}')
            try:
                release.verify(False)
            except HostError:
                checks.append('release anchor still enforced')
            else:
                raise AssertionError('Changed manifest passed')

    report = {'status': 'PASS', 'checks': checks, 'paid_calls': 0}
    (STATE / 'release-integrity-results.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
