#!/usr/bin/env python3
"""home-server web root: static files behind Tailscale Serve, with per-path access control.

- binds to 127.0.0.1 only; reachable solely through Tailscale Serve, and every connection must come from Tailscale's
  own process (checked with netstat + ps), so other users and programs on the Mac can't connect and fake its headers
- every request must carry Tailscale-User-Login (set by Tailscale Serve for tailnet users)
- access.json decides who may open which path (longest matching prefix wins):
    {"default": ["you@example.com"], "paths": {"/axella/": ["you@example.com"]}}
  an empty or missing list means "nobody" (fail closed); the Mac's own node login is never allowed
- only an allow-list of paths is served (dashboard files, digests/, calls/), checked on the decoded path
- /axella/status.json: what the watchdog (setup/watchdog.py) found – is the owner logged in, is the action service up –
  so the dashboard can say why it is paused. Runs best as a LaunchDaemon, so the page loads even with nobody logged in.
"""
import json
import os
import posixpath
import re
import sys
from urllib.parse import unquote
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))          # .../home-server/www
ACCESS = os.path.join(ROOT, 'access.json')
PORT = int(os.environ.get('WWW_PORT', '8787'))


def access():
    try:
        with open(ACCESS, encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def allowed(path, login):
    """Fail closed: a missing or empty list lets nobody in, and the Mac's own node login ("node:<name>") never –
    any program on the Mac can reach the tailnet URL, so it proves nothing about who is asking."""
    if not login or login.startswith('node:'):
        return False
    cfg = access()
    rules = cfg.get('paths', {})
    match = max((p for p in rules if path.startswith(p)), key=len, default=None)
    users = rules[match] if match is not None else cfg.get('default', [])
    return bool(users) and login in users


TAILSCALE_BIN = '/Applications/Tailscale.app/Contents/MacOS/Tailscale'
_WHOIS_CACHE = {}


import socket as _socket
_LOCAL = {'at': 0, 'ips': set()}


def _local_ips():
    """IP addresses on this Mac's own interfaces (incl. its Tailscale 100.x / fd7a: address)."""
    import subprocess as _sp, time as _t, re as _re
    if _t.time() - _LOCAL['at'] > 300:
        try:
            out = _sp.run(['/sbin/ifconfig'], capture_output=True, text=True, timeout=5).stdout
            _LOCAL['ips'] = set(_re.findall(r'inet6? ([0-9a-fA-F:.]+)', out)) | {'127.0.0.1', '::1'}
        except Exception:
            _LOCAL['ips'] = {'127.0.0.1', '::1'}
        _LOCAL['at'] = _t.time()
    return _LOCAL['ips']


def tailnet_login(headers):
    """Who is asking? Prefer Tailscale-User-Login; otherwise ask Tailscale who owns the
    source address that Tailscale Serve put in X-Forwarded-For. None = not a tailnet user."""
    import subprocess as _sp, time as _t, json as _j
    login = headers.get('Tailscale-User-Login', '')
    if login:
        return login
    ip = (headers.get('X-Forwarded-For', '') or '').split(',')[-1].strip()   # Serve appends the real client: take the last
    if not ip:
        return None
    if ip in _local_ips():
        # request from this Mac itself (tagged node, no user): the Tailscale CLI can't be used from launchd here
        return 'node:' + _socket.gethostname().split('.')[0]
    hit = _WHOIS_CACHE.get(ip)
    if hit and _t.time() - hit[1] < 300:
        return hit[0]
    try:
        out = _sp.run([TAILSCALE_BIN, 'whois', '--json', ip], capture_output=True, text=True, timeout=5)
        data = _j.loads(out.stdout) if out.returncode == 0 else {}
        node = data.get('Node') or {}
        login = (data.get('UserProfile') or {}).get('LoginName') or None
        if node.get('Tags') or login == 'tagged-devices':
            # tagged devices (e.g. the Mac mini itself, tag:server) have no user: identify the machine
            name = node.get('ComputedName') or (node.get('Name') or '').split('.')[0]
            login = 'node:' + name if name else None
    except Exception:
        login = None
    _WHOIS_CACHE[ip] = (login, _t.time())
    return login


# Served from an ALLOW-list, checked on the decoded, normalised path (what the file server will actually open) –
# never a blocklist on the raw path: "/axella/%73tate/…" decodes to "state/".
ALLOW = [re.compile(x) for x in (
    r'^/$', r'^/index\.html$',
    r'^/axella/?$', r'^/axella/(index\.html|sw\.js|manifest\.webmanifest)$',
    r'^/axella/(assets|icons)/[\w-][\w.-]*$',
    r'^/axella/digests/$', r'^/axella/digests/[\w-]+\.(md|json)$',
    r'^/axella/digests/archive/$', r'^/axella/digests/archive/\d{4}-\d{2}/$',
    r'^/axella/digests/archive/\d{4}-\d{2}/[\w-]+\.(md|json)$',
    r'^/axella/calls/$', r'^/axella/calls/[\w-]+\.json$',
)]


def servable(raw_path, fs_path):
    path = unquote(raw_path)
    if '\x00' in path or '\\' in path:
        return False
    norm = posixpath.normpath(path) + ('/' if path.endswith('/') and path != '/' else '')
    if norm != path or not any(r.match(norm) for r in ALLOW):
        return False                    # anything with //, /./, /../ or not on the list
    if any(seg.startswith(('.', '_')) for seg in norm.split('/') if seg):
        return False
    real = os.path.realpath(fs_path)
    roots = [os.path.realpath(ROOT)]
    return any(real == r or real.startswith(r + os.sep) for r in roots + [os.path.realpath(os.path.join(ROOT, 'axella'))])


class Handler(SimpleHTTPRequestHandler):
    def _deny(self, code, msg):
        body = f'<!doctype html><meta charset="utf-8"><title>{code}</title><p style="font:16px system-ui;padding:2rem">{msg}</p>'.encode()
        self.send_response(code)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    protocol_version = 'HTTP/1.1'      # keep-alive: Serve reuses a connection, so the peer check runs once per connection

    def _check(self):
        login = tailnet_login(self.headers)
        path = self.path.split('?')[0].split('#')[0]
        if not login:
            self._deny(403, 'Only reachable through Tailscale.')
            return False
        if not servable(path, self.translate_path(path)):
            self._deny(404, 'Not found.')
            return False
        if not allowed(path, login):
            self.log_message('denied %s for %s', path, login)
            self._deny(403, f'{login} has no access to this page.')
            return False
        return True

    def _status(self):
        """The watchdog's last check (state/watchdog.json), with the same login and access rules as the dashboard."""
        login = tailnet_login(self.headers)
        if not login or not allowed('/axella/', login):
            return self._deny(403, 'No access.')
        try:
            with open(os.path.join(ROOT, 'axella', 'state', 'watchdog.json'), encoding='utf-8') as f:
                w = json.load(f)
            st = {k: w.get(k) for k in ('at', 'ok', 'session', 'actions', 'problem', 'since')}
            st['sources'] = [{'name': n, 'problem': o.get('problem'), 'since': o.get('since')}
                             for n, o in (w.get('source_state') or {}).items() if isinstance(o, dict) and o.get('problem')]
        except (OSError, ValueError):
            st = {'ok': None, 'problem': None}               # no watchdog installed
        body = json.dumps(st).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.split('?')[0] == '/axella/status.json':
            return self._status()
        if self._check():
            super().do_GET()

    def do_HEAD(self):
        if self._check():
            super().do_HEAD()

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        super().end_headers()

    def log_request(self, code='-', size='-'):
        c = getattr(code, 'value', code)            # only refusals and errors – not every file the dashboard loads
        if isinstance(c, int) and c < 400:
            return
        super().log_request(code, size)

    def log_message(self, fmt, *args):
        sys.stderr.write('%s %s\n' % (_t_peer.strftime('%Y-%m-%dT%H:%M:%S'), fmt % args))


# ---------- only Tailscale Serve may connect (security review item 2) ----------
# Both services listen on 127.0.0.1, where any program on the Mac could connect and send Tailscale's identity headers
# itself. So every new connection is checked: macOS' `netstat -anv` names the process that owns the other end, and
# only Tailscale's network extension (a root process under /Library/SystemExtensions/) is let in. Another user or a
# script can't run as root, so it can't pass. Fails closed. (Unix sockets would be cleaner, but the sandboxed
# Tailscale app can't proxy to them – tested 1 Nov 2026, HTTP 502.)
import re as _re_peer
import subprocess as _sp_peer
import threading as _th_peer
import time as _t_peer

_PEER = {'lock': _th_peer.Lock(), 'map': {}, 'at': 0.0}
_NETSTAT_RE = _re_peer.compile(r'^tcp4\s+\d+\s+\d+\s+127\.0\.0\.1\.(\d+)\s+127\.0\.0\.1\.(\d+)\s+ESTABLISHED\s+\d+\s+\d+\s+\d+\s+\d+\s+(.+?):(\d+)\s')
_TS_PATHS = ('/Library/SystemExtensions/', '/Applications/Tailscale.app/')


def _netstat_map():
    """{(client port, server port): pid} for every established 127.0.0.1 connection."""
    out = _sp_peer.run(['/usr/sbin/netstat', '-anv', '-p', 'tcp'], capture_output=True, text=True, timeout=5).stdout
    m = {}
    for line in out.splitlines():
        r = _NETSTAT_RE.match(line)
        if r:
            m[(int(r.group(1)), int(r.group(2)))] = int(r.group(4))
    return m


def _is_tailscale(pid):
    """Asked fresh for every connection (no cache): a PID can be reused after Tailscale restarts."""
    out = _sp_peer.run(['/bin/ps', '-o', 'uid=,comm=', '-p', str(pid)], capture_output=True, text=True, timeout=5).stdout.strip()
    uid, _, comm = out.partition(' ')
    return uid.strip() == '0' and 'io.tailscale.ipn' in comm and comm.strip().startswith(_TS_PATHS)


def peer_is_tailscale(client_port, server_port, state_dir=None):
    """True only if the program on the other end of this 127.0.0.1 connection is Tailscale.
    The owner lookup always comes from a netstat snapshot taken AFTER this connection was accepted – an older
    snapshot could still list a closed Tailscale connection whose source port a local program has since reused."""
    if os.environ.get('AXELLA_PEER_CHECK') == '0':            # tests on other systems only
        return True
    if state_dir:
        off = os.path.join(state_dir, 'peer-check.off')
        try:
            if _t_peer.time() - os.path.getmtime(off) < 86400:
                sys.stderr.write('peer check OFF (state/peer-check.off) – any local program can connect\n')
                return True
            sys.stderr.write('ignoring state/peer-check.off: older than 24 h\n')
        except OSError:
            pass
    key = (int(client_port), int(server_port))
    accepted = _t_peer.time()
    try:
        for attempt in range(3):
            with _PEER['lock']:
                if _PEER['at'] < accepted:                     # only a snapshot newer than this connection counts
                    _PEER['map'], _PEER['at'] = _netstat_map(), _t_peer.time()
                pid = _PEER['map'].get(key)
            if pid is not None:
                ok = _is_tailscale(pid)
                if not ok:
                    sys.stderr.write(f'refused 127.0.0.1:{client_port} → {server_port}: process {pid} is not Tailscale\n')
                return ok
            _t_peer.sleep(0.03)
            accepted = _t_peer.time()                          # next try: a fresh snapshot again
        sys.stderr.write(f'refused 127.0.0.1:{client_port} → {server_port}: owner not found\n')
    except Exception as e:
        sys.stderr.write(f'refused 127.0.0.1:{client_port} → {server_port}: peer check failed: {str(e)[:200]}\n')
    return False


class TailscaleOnlyServer(ThreadingHTTPServer):
    state_dir = None

    def verify_request(self, request, client_address):
        return peer_is_tailscale(client_address[1], self.server_address[1], self.state_dir)


if __name__ == '__main__':
    os.umask(0o077)
    TailscaleOnlyServer.state_dir = os.path.join(ROOT, '..', 'axella', 'state')
    TailscaleOnlyServer(('127.0.0.1', PORT), partial(Handler, directory=ROOT)).serve_forever()
