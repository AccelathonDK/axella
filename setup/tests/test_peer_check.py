"""Web/API access checks: peer check (only Tailscale may connect), node login, and the web root allow-list.
Run: python3 setup/tests/test_peer_check.py
Uses the web server's copy of the check (same code as axella-actions.py); netstat and ps are faked."""
import importlib.util
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location('www_server', os.path.join(HERE, '..', 'www-template', 'www-server.py'))
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)
os.environ.pop('AXELLA_PEER_CHECK', None)

TS, CURL = 933, 777
PS = {TS: '    0 /Library/SystemExtensions/X/io.tailscale.ipn.macsys.network-extension.sys', CURL: '  501 /usr/bin/curl'}


class R:
    def __init__(self, out):
        self.stdout = out


snapshots = []


def fake_run(cmd, **_):
    if 'netstat' in cmd[0]:
        rows = snapshots.pop(0) if snapshots else []
        return R('\n'.join('tcp4 0 0 127.0.0.1.%d 127.0.0.1.%d ESTABLISHED 0 0 1 1 %s:%d 00182 x' % (c, s, n, p)
                           for c, s, n, p in rows))
    return R(PS.get(int(cmd[-1]), ''))


w._sp_peer.run = fake_run
ok = True


def check(name, cond):
    global ok
    print(('PASS ' if cond else 'FAIL ') + name)
    ok = ok and cond


# 1. Tailscale's connection is let in, curl's is not
snapshots[:] = [[(50001, 8788, 'io.tailscale.ipn', TS)]]
check('tailscale accepted', w.peer_is_tailscale(50001, 8788))
snapshots[:] = [[(50002, 8788, 'curl', CURL)]]
check('curl refused', not w.peer_is_tailscale(50002, 8788))

# 2. A stale snapshot must not be reused: Tailscale used port 50003 earlier; now curl reuses that port
snapshots[:] = [[(50003, 8788, 'io.tailscale.ipn', TS)]]
check('earlier tailscale connection accepted', w.peer_is_tailscale(50003, 8788))
time.sleep(0.01)
snapshots[:] = [[(50003, 8788, 'curl', CURL)]] * 3
check('reused port by curl refused (fresh snapshot)', not w.peer_is_tailscale(50003, 8788))

# 3. A process that only calls itself io.tailscale.ipn but isn't root is refused
PS[888] = '  501 /Users/x/io.tailscale.ipn'
snapshots[:] = [[(50004, 8788, 'io.tailscale.ipn', 888)]]
check('fake name refused', not w.peer_is_tailscale(50004, 8788))

# 4. No owner found → refused
snapshots[:] = [[], [], []]
check('unknown owner refused', not w.peer_is_tailscale(50005, 8788))

# 5. The node login and empty lists never pass access control
w.access = lambda: {'default': [], 'paths': {'/axella/': ['you@example.com', 'node:mac']}}
check('owner allowed', w.allowed('/axella/', 'you@example.com'))
check('node login refused even when listed', not w.allowed('/axella/', 'node:mac'))
check('empty list refuses', not w.allowed('/other/', 'you@example.com'))

# 6. The web root only serves its allow-list, judged on the decoded path
import tempfile
root = tempfile.mkdtemp()
os.makedirs(os.path.join(root, 'axella', 'digests'))
w.ROOT = root
def fs(p): return os.path.join(root, *[x for x in p.split('/') if x])
for good in ('/', '/axella/', '/axella/sw.js', '/axella/digests/', '/axella/digests/2026-11-01-0731.json', '/axella/calls/config.json'):
    check('serves ' + good, w.servable(good, fs(good)))
for bad in ('/axella/%73tate/voice-token', '/axella/%73tate/vapid%2Ejson', '/axella/%73etup/actions-config%2Ejson',
            '/axella/contacts%2Emd', '/axella/AXELLA%2Emd', '/axella/%2Egit/config', '/access%2Ejson',
            '/axella/contacts-cleanup/a.vcf', '/axella/docs/Axella-overview.pdf', '/axella/tools/public-release/blocklist.txt',
            '/axella/digests/_trial/spoken.tmp', '/axella/digests/%2e%2e/state/x', '/axella//state/x', '/www-server.py'):
    check('refuses ' + bad, not w.servable(bad, fs(bad)))

sys.exit(0 if ok else 1)
