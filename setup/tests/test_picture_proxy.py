#!/usr/bin/env python3
"""Picture proxy (security review 3, P2-3): the address that was checked is the one connected to – a sender's DNS
can't swap in a home-network address between check and connect. No network is used.
Run: python3 setup/tests/test_picture_proxy.py"""
import os
import socket
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import mailsearch as M  # noqa: E402

fails = 0


def ok(c, label):
    global fails
    print(('  ok   ' if c else '  FAIL ') + label)
    fails += 0 if c else 1


def rebinding():
    answers = iter(['93.184.216.34', '192.168.1.1', '192.168.1.1', '192.168.1.1'])
    return lambda host, port, *a: [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (next(answers), port))]


connected = []


def fake_connect(addr, timeout):
    connected.append(addr[0])
    raise OSError('test: no network')


u = 'http://pics.attacker.example/pixel.png'
try:
    M.fetch_image(u, M._sign(u), resolve=rebinding(), connect=fake_connect)
except M.SearchError:
    pass
ok(connected == ['93.184.216.34'], 'DNS rebinding: connects only to the checked public address (%s)' % connected)

connected.clear()
mixed = lambda host, port, *a: [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', port)),
                                (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('10.0.0.5', port))]
try:
    M.fetch_image(u, M._sign(u), resolve=mixed, connect=fake_connect)
    ok(False, 'mixed public/private answer refused')
except M.SearchError as e:
    ok(not connected and 'not allowed' in str(e), 'a name that also resolves to a private address is refused, no connection')

for bad in ('http://100.64.0.1/x.png', 'http://[::1]/x.png', 'http://169.254.169.254/x.png', 'file:///etc/passwd'):
    connected.clear()
    try:
        M.fetch_image(bad, M._sign(bad), connect=fake_connect)
        ok(False, 'refused: ' + bad)
    except M.SearchError:
        ok(not connected, 'refused without connecting: ' + bad)

try:
    M.fetch_image(u, 'wrong-signature', resolve=rebinding(), connect=fake_connect)
    ok(False, 'unsigned link refused')
except M.SearchError:
    ok(True, 'unsigned link refused')

M._IMG_CACHE.clear()
for i in range(30):
    M._cache_put('u%d' % i, ('image/png', b'x' * (4 * 2**20)))
ok(sum(len(v[1]) for v in M._IMG_CACHE.values()) <= M.CACHE_BYTES, 'cache stays under %d MB' % (M.CACHE_BYTES >> 20))
print('PASS' if not fails else 'FAIL (%d)' % fails)
sys.exit(1 if fails else 0)
