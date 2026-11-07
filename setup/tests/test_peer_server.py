#!/usr/bin/env python3
"""The action service under a page load (axella-actions.TailscaleOnlyServer): 20 connections at once all get an
answer although the peer check is slow (it now runs in each connection's own thread, with a backlog of 64 – before,
with 5 and the check on the accept loop, the rest were reset and Tailscale Serve answered 502), and a connection the
peer check refuses (or that makes the check fail) is still closed without an answer. The check itself is faked.
Run: python3 setup/tests/test_peer_server.py"""
import importlib.util
import os
import socket
import sys
import threading
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
spec = importlib.util.spec_from_file_location('axa', os.path.join(HERE, 'axella-actions.py'))
A = importlib.util.module_from_spec(spec)
spec.loader.exec_module(A)

fails = 0


def ok(c, label):
    global fails
    print(('  ok   ' if c else '  FAIL ') + label)
    fails += 0 if c else 1


refuse, broken = set(), set()


def fake_check(client_port, server_port, state_dir=None):
    time.sleep(0.3)                       # a slow netstat + ps
    if client_port in broken:
        raise RuntimeError('netstat failed')
    return client_port not in refuse


A.peer_is_tailscale = fake_check
sys.stderr = open(os.devnull, 'w')       # the 403 log lines of the fake requests
srv = A.TailscaleOnlyServer(('127.0.0.1', 0), A.Handler)
port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
ok(srv.request_queue_size >= 64, 'a backlog of 64 (was 5)')


def ask(out, i, mark=None):
    s = socket.create_connection(('127.0.0.1', port), timeout=10)
    if mark == 'refuse':
        refuse.add(s.getsockname()[1])
    if mark == 'broken':
        broken.add(s.getsockname()[1])
    try:
        s.sendall(b'GET /health HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n')
        got = b''
        while True:                       # read the whole answer, so the server never writes into a closed socket
            b = s.recv(4096)
            if not b:
                break
            got += b
        out[i] = got
    except OSError as e:
        out[i] = e
    finally:
        s.close()


out = {}
t0 = time.time()
ts = [threading.Thread(target=ask, args=(out, i)) for i in range(20)]
[t.start() for t in ts]
[t.join() for t in ts]
took = time.time() - t0
answered = sum(1 for v in out.values() if isinstance(v, bytes) and v.startswith(b'HTTP/'))
ok(answered == 20, '20 connections at once: all 20 answered (%d)' % answered)
ok(took < 3, 'in parallel, not one after another (%.1f s for 20 checks of 0.3 s)' % took)
out = {}
ask(out, 'r', 'refuse')
ok(out['r'] == b'' or isinstance(out['r'], OSError), 'a refused peer gets no answer – the connection is closed')
out = {}
ask(out, 'b', 'broken')
ok(out['b'] == b'' or isinstance(out['b'], OSError), 'a peer check that fails refuses (fails closed)')
srv.shutdown()
src = open(os.path.join(HERE, 'mail_tidy.py'), encoding='utf-8').read()
ok('set st ' not in src and '(st is' not in src, "Keep Mail tidy's script has no variable \"st\" (an ordinal suffix in AppleScript – it didn't compile)")
if os.path.exists('/usr/bin/osacompile'):
    import subprocess
    import tempfile
    import mail_tidy
    f = tempfile.mktemp(suffix='.scpt')
    r = subprocess.run(['/usr/bin/osacompile', '-o', f, '-e', A.FIND_MESSAGE + mail_tidy.MARK_SCRIPT_RUN], capture_output=True, text=True)
    ok(r.returncode == 0, "Keep Mail tidy's script compiles (osacompile)%s" % ('' if r.returncode == 0 else ': ' + r.stderr.strip()[:200]))
else:
    print('  skip the osacompile check (not a Mac)')

print('PASS' if not fails else 'FAIL (%d)' % fails)
sys.exit(1 if fails else 0)
