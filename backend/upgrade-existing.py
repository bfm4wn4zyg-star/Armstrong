"""Conservative in-place update. Run only inside the user's authenticated Ubuntu terminal."""
from pathlib import Path
import base64
import argparse
import re
import hashlib
import json
import os
import py_compile
import shutil
import signal
import socket
import sqlite3
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

# Filled from verified local source by prepare_remote.py.
SERVER_SHA = 'c3053f4bb1079d6abc98d2f1b928d1939afe4a2369a3a44f30a1b7fcb030a068'
TEST_SHA = '972182a85fa37201c67e4e3cbe4959d11311389c9f6698b12e3cdc6216448839'
parser = argparse.ArgumentParser()
parser.add_argument('--pid', type=int, required=True)
parser.add_argument('--ref', required=True)
cli = parser.parse_args()
assert re.fullmatch(r'[0-9a-f]{7,40}', cli.ref), 'Invalid release ref'
def download(name, expected):
    urls = ['https://raw.githubusercontent.com/bfm4wn4zyg-star/Armstrong/' + cli.ref + '/backend/' + name, 'https://bfm4wn4zyg-star.github.io/Armstrong/backend/' + name + '?v=' + cli.ref]
    for url in urls:
        try:
            source = urllib.request.urlopen(url, timeout=20).read()
            if hashlib.sha256(source).hexdigest() == expected:
                return source
        except (OSError, urllib.error.URLError):
            pass
    raise RuntimeError('Could not download verified release file: ' + name)
EXPECTED_OLD_SHA = "07a0517996814bd5b9895df0e9f45c2e2212d7f87d9aef34ecfce03c3ee7a824"

os.umask(0o077)
pid = cli.pid
proc = Path('/proc') / str(pid)
args = [x.decode() for x in (proc / 'cmdline').read_bytes().split(bytes([0])) if x]
server_file = next(Path(x).resolve() for x in args if x.endswith('/server.py'))
base = (Path.home() / '.local/share/armstrong-team').resolve()
assert server_file.is_relative_to(base / 'releases'), 'Unexpected service path'
original = server_file.read_bytes()
assert hashlib.sha256(original).hexdigest() == EXPECTED_OLD_SHA, 'Source changed; update stopped'
env = dict(x.decode().split('=', 1) for x in (proc / 'environ').read_bytes().split(bytes([0])) if b'=' in x)
cwd = os.readlink(proc / 'cwd')
database = Path(env.get('ARMSTRONG_DB', str(server_file.parent / 'team.sqlite3'))).resolve()
assert database.is_file(), 'Database path not found; update stopped'
port = int(args[args.index('--port') + 1])
api_origin = args[args.index('--app-origin') + 1]

staging = Path(tempfile.mkdtemp(prefix='armstrong-prerelease-20261124-'))
candidate = staging / 'server.py'
candidate.write_bytes(download('server.py', SERVER_SHA))
test = staging / 'backend_regression.py'
test_source = download('tests/backend_regression.py', TEST_SHA).decode()
test.write_text(test_source.replace("source = Path(__file__).resolve().parent.parent / 'server.py'", 'source = Path(' + repr(str(candidate)) + ')'), encoding='utf-8')
helper_source = Path(__file__).read_bytes() if '__file__' in globals() else globals().get('s')
assert isinstance(helper_source, bytes), 'Verified upgrade source is unavailable'
(staging / 'upgrade-existing.py').write_bytes(helper_source)
py_compile.compile(str(candidate), doraise=True)
subprocess.run([args[0], str(test)], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=40)
print('REMOTE_TESTS_PASS:17', flush=True)

stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
backup = base / 'backups' / ('prerelease-' + stamp)
backup.mkdir(parents=True, exist_ok=False)
shutil.copy2(server_file, backup / 'server.py')
with sqlite3.connect(database) as con:
    before = con.execute('SELECT kind,revision,payload FROM records ORDER BY kind').fetchall()
    with sqlite3.connect(backup / 'team.sqlite3') as target:
        con.backup(target)
        assert target.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
before_hash = hashlib.sha256(repr(before).encode()).hexdigest()
print('BACKUP_OK', backup, flush=True)

def health():
    try:
        request = urllib.request.Request('http://127.0.0.1:%d/api/bootstrap' % port,
                                         headers={'Origin': api_origin})
        urllib.request.urlopen(request, timeout=2)
    except urllib.error.HTTPError as error:
        return error.code == 401
    except (OSError, urllib.error.URLError):
        return False
    return False

def start():
    log = (base / 'prerelease-service.log').open('ab')
    return subprocess.Popen(['/usr/bin/flock', '-n', str(base / 'service.lock'), *args],
                            cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=log,
                            stderr=subprocess.STDOUT, start_new_session=True)

pending = server_file.with_name('server.py.prerelease-pending')
pending.write_bytes(candidate.read_bytes())
shutil.copymode(server_file, pending)
os.replace(pending, server_file)
os.kill(pid, signal.SIGTERM)
for _ in range(50):
    if not proc.exists():
        break
    time.sleep(.1)
time.sleep(.4)
new_process = start()
for _ in range(50):
    if health():
        break
    time.sleep(.2)
else:
    # Restore code only; never overwrite the live database with a backup.
    shutil.copy2(backup / 'server.py', server_file)
    if new_process.poll() is None:
        os.killpg(new_process.pid, signal.SIGTERM)
        new_process.wait(timeout=5)
    start()
    raise RuntimeError('New service failed health check; original code restored')

with sqlite3.connect(database) as con:
    after = con.execute('SELECT kind,revision,payload FROM records ORDER BY kind').fetchall()
    assert con.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
print('SERVICE_OK:401_UNAUTHENTICATED', flush=True)
print('RECORDS_UNCHANGED' if hashlib.sha256(repr(after).encode()).hexdigest() == before_hash else 'RECORDS_CHANGED_DURING_DEPLOY_REVIEW_REQUIRED', flush=True)
print('NEW_SOURCE_SHA', hashlib.sha256(server_file.read_bytes()).hexdigest(), flush=True)
print('DEPLOY_COMPLETE', flush=True)
