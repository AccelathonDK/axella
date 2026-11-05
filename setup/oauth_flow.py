"""Signing in to the meeting services (Microsoft Teams, Google Meet, Zoom) for Calendar → online meetings.

One flow for all: authorization code with PKCE (S256) and a one-time `state`. The redirect goes to the dashboard's own
Tailscale Serve address (…/axella/api/oauth_callback), so nothing is opened to the internet. Each installation uses its
own app registrations: the client id and secret are entered once in Terminal (tools/meeting-services.py) and kept
in the macOS Keychain, like the tokens. Neither is ever in state/, git, a log or anything a Claude run can read.

Keychain items (login keychain, the user that runs the action service):
  service "axella-oauth-app",   account <provider>  → {"client_id", "client_secret", "tenant"?}
  service "axella-oauth-token", account <provider>  → {"access_token", "refresh_token", "expires_at", "account"}
Values are written through `security -i` on stdin (hex), so they never appear in a process list.
"""
import base64
import hashlib
import json
import secrets
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

APP_SERVICE, TOKEN_SERVICE = 'axella-oauth-app', 'axella-oauth-token'
PENDING_SECS = 600

PROVIDERS = {
    'teams': {
        'label': 'Microsoft Teams',
        'authorize': 'https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize',
        'token': 'https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token',
        'scope': 'offline_access User.Read Calendars.ReadWrite OnlineMeetings.ReadWrite',
        'revoke_page': 'https://myapps.microsoft.com',
        'client_auth': 'body',
    },
    'google_meet': {
        'label': 'Google Meet',
        'authorize': 'https://accounts.google.com/o/oauth2/v2/auth',
        'token': 'https://oauth2.googleapis.com/token',
        'scope': 'https://www.googleapis.com/auth/meetings.space.created',
        'extra': {'access_type': 'offline', 'prompt': 'consent'},
        'revoke_page': 'https://myaccount.google.com/connections',
        'client_auth': 'body',
    },
    'zoom': {
        'label': 'Zoom',
        'authorize': 'https://zoom.us/oauth/authorize',
        'token': 'https://zoom.us/oauth/token',
        'scope': '',                     # Zoom takes the scopes from the app's own settings
        'revoke_page': 'https://marketplace.zoom.us/user/installed',
        'client_auth': 'basic',
    },
}


class Bad(Exception):
    pass


# ---------- the Keychain ----------
class Keychain:
    """The macOS Keychain through the `security` tool. Replaceable in tests (a dict)."""

    def get(self, service, account):
        try:
            r = subprocess.run(['security', 'find-generic-password', '-s', service, '-a', account, '-w'],
                               capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            return None
        if r.returncode != 0:
            return None
        try:
            return json.loads(r.stdout.strip())
        except ValueError:
            return None

    def set(self, service, account, value):
        data = json.dumps(value, separators=(',', ':')).encode()
        cmd = 'add-generic-password -U -s %s -a %s -X %s\n' % (service, account, data.hex())
        r = subprocess.run(['security', '-i'], input=cmd, capture_output=True, text=True, timeout=10)
        if r.returncode != 0 or 'error' in (r.stderr or '').lower():
            raise Bad('could not save to the Keychain')

    def delete(self, service, account):
        subprocess.run(['security', 'delete-generic-password', '-s', service, '-a', account], capture_output=True, timeout=10)


def http(method, url, headers=None, body=None, form=None, timeout=20):
    """→ (status, dict). JSON in and out, or a form body for the token endpoints."""
    h = dict(headers or {})
    data = None
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        h['Content-Type'] = 'application/x-www-form-urlencoded'
    elif body is not None:
        data = json.dumps(body).encode()
        h['Content-Type'] = 'application/json'
    h.setdefault('Accept', 'application/json')
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read(2_000_000)
            status = r.status
    except urllib.error.HTTPError as e:
        raw, status = e.read(200_000), e.code
    except (urllib.error.URLError, OSError) as e:
        raise Bad('could not reach the service (%s)' % type(e).__name__)
    try:
        out = json.loads(raw.decode('utf-8', 'replace')) if raw else {}
    except ValueError:
        out = {}
    return status, out if isinstance(out, dict) else {'value': out}


def _challenge(verifier):
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()


class OAuth:
    def __init__(self, keychain=None, http_fn=None, clock=time.time, note=None):
        self.kc = keychain or Keychain()
        self.http = http_fn or http
        self.clock = clock
        self.note = note or (lambda *a: None)          # (provider, action) → "What leaves my home"
        self._pending = {}
        self._lock = threading.Lock()

    def _p(self, provider):
        if provider not in PROVIDERS:
            raise Bad('unknown meeting service')
        return PROVIDERS[provider]

    def app(self, provider):
        a = self.kc.get(APP_SERVICE, provider)
        return a if isinstance(a, dict) and a.get('client_id') else None

    def _url(self, provider, which):
        a = self.app(provider) or {}
        return self._p(provider)[which].replace('{tenant}', urllib.parse.quote(a.get('tenant') or 'organizations', safe=''))

    # ---- connect
    def start(self, provider, redirect):
        p = self._p(provider)
        a = self.app(provider)
        if not a:
            raise Bad('%s is not set up yet – run tools/meeting-services.py on the Mac mini' % p['label'])
        if not redirect.startswith('https://') or not redirect.endswith('/api/oauth_callback'):
            raise Bad('the dashboard address must be its https Tailscale address')
        state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
        with self._lock:
            now = self.clock()
            self._pending = {k: v for k, v in self._pending.items() if now - v['at'] < PENDING_SECS}
            if len(self._pending) > 20:
                raise Bad('too many sign-ins started – wait a few minutes')
            self._pending[state] = {'provider': provider, 'verifier': verifier, 'redirect': redirect, 'at': now}
        q = {'response_type': 'code', 'client_id': a['client_id'], 'redirect_uri': redirect, 'state': state,
             'code_challenge': _challenge(verifier), 'code_challenge_method': 'S256'}
        if p['scope']:
            q['scope'] = p['scope']
        q.update(p.get('extra') or {})
        return self._url(provider, 'authorize') + '?' + urllib.parse.urlencode(q)

    def callback(self, state, code, error=None, desc=None):
        """The redirect back: only a state this process handed out, within 10 minutes, once."""
        with self._lock:
            pend = self._pending.pop(str(state or ''), None)
        if not pend or self.clock() - pend['at'] > PENDING_SECS:
            raise Bad('this sign-in link is unknown or too old – start Connect again')
        provider = pend['provider']
        if error:
            d = str(desc or '')[:2000]
            if provider == 'teams' and ('AADSTS90094' in d or 'AADSTS65001' in d or 'admin' in d.lower() or 'approval' in d.lower()):
                self.kc.set(TOKEN_SERVICE, provider, {'approval': 'needs_approval', 'at': self.clock()})
                raise Bad('Your IT has to approve Axella for your work account – send them the request from SETUP "Meeting services"')
            raise Bad('%s said no (%s)' % (PROVIDERS[provider]['label'], str(error)[:60]))
        if not code or len(str(code)) > 4000:
            raise Bad('no sign-in code came back')
        form = {'grant_type': 'authorization_code', 'code': str(code), 'redirect_uri': pend['redirect'],
                'code_verifier': pend['verifier']}
        self._token(provider, form)
        return provider

    def _token(self, provider, form):
        a = self.app(provider)
        if not a:
            raise Bad('not set up')
        p = self._p(provider)
        headers = {}
        if p['client_auth'] == 'basic':
            headers['Authorization'] = 'Basic ' + base64.b64encode(('%s:%s' % (a['client_id'], a.get('client_secret') or '')).encode()).decode()
        else:
            form = dict(form, client_id=a['client_id'])
            if a.get('client_secret'):
                form['client_secret'] = a['client_secret']
        if p['scope'] and form.get('grant_type') == 'refresh_token' and provider == 'teams':
            form['scope'] = p['scope']
        self.note(provider, 'sign-in' if form.get('grant_type') == 'authorization_code' else 'token refresh')
        status, out = self.http('POST', self._url(provider, 'token'), headers=headers, form=form)
        if status != 200 or not out.get('access_token'):
            err = str(out.get('error') or status)[:60]
            raise Bad('%s refused the sign-in (%s)' % (p['label'], err))
        old = self.kc.get(TOKEN_SERVICE, provider) or {}
        tok = {'approval': None, 'access_token': out['access_token'], 'refresh_token': out.get('refresh_token') or old.get('refresh_token'),
               'expires_at': self.clock() + int(out.get('expires_in') or 3600), 'account': old.get('account'),
               'connected': old.get('connected') or self.clock()}
        self.kc.set(TOKEN_SERVICE, provider, tok)
        return tok

    def access_token(self, provider):
        tok = self.kc.get(TOKEN_SERVICE, provider)
        if not tok or not tok.get('access_token'):
            raise Bad('%s is not connected' % self._p(provider)['label'])
        if tok.get('expires_at', 0) - 60 > self.clock():
            return tok['access_token']
        if not tok.get('refresh_token'):
            raise Bad('%s needs you to connect again' % self._p(provider)['label'])
        try:
            return self._token(provider, {'grant_type': 'refresh_token', 'refresh_token': tok['refresh_token']})['access_token']
        except Bad:
            raise Bad('%s needs you to connect again' % self._p(provider)['label'])

    def set_account(self, provider, account):
        tok = self.kc.get(TOKEN_SERVICE, provider) or {}
        if tok:
            tok['account'] = str(account or '')[:200] or None
            self.kc.set(TOKEN_SERVICE, provider, tok)

    def status(self, provider):
        p = self._p(provider)
        if not self.app(provider):
            return {'state': 'not_set_up', 'label': p['label'], 'why': 'Register the app once – see SETUP "Meeting services"'}
        tok = self.kc.get(TOKEN_SERVICE, provider)
        if tok and tok.get('approval') == 'needs_approval':
            return {'state': 'needs_approval', 'label': p['label'], 'why': 'Waiting for your IT to approve creating meetings'}
        if not tok or not tok.get('access_token'):
            return {'state': 'not_connected', 'label': p['label']}
        return {'state': tok.get('approval') or 'connected', 'label': p['label'], 'account': tok.get('account')}

    def set_approval(self, provider, state):
        """'needs_approval' when the work tenant answers that IT must approve the app; None when it works again."""
        tok = self.kc.get(TOKEN_SERVICE, provider) or {}
        if tok and tok.get('approval') != state:
            tok['approval'] = state
            self.kc.set(TOKEN_SERVICE, provider, tok)

    def disconnect(self, provider):
        p = self._p(provider)
        self.kc.delete(TOKEN_SERVICE, provider)
        return {'message': 'Disconnected – also remove Axella\'s access on %s\'s own page' % p['label'], 'revoke_page': p['revoke_page']}
