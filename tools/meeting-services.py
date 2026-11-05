#!/usr/bin/env python3
"""Calendar → meeting services and invites: enter the app registrations and the iCloud app password ONCE, here in
Terminal on the Mac mini. Everything goes into the macOS Keychain – never into a file, git, the dashboard or a log.

  cd ~/dev/own/home-server/axella && python3 tools/meeting-services.py            # what is set up (yes/no only)
  python3 tools/meeting-services.py teams          # Microsoft Teams: the Entra app's client id, secret, tenant
  python3 tools/meeting-services.py google_meet    # Google Meet: the Google Cloud OAuth client id and secret
  python3 tools/meeting-services.py zoom           # Zoom: the General app's client id and secret
  python3 tools/meeting-services.py icloud         # iCloud invites: your Apple Account address and an app-specific password
  python3 tools/meeting-services.py remove <name>  # take one out again (and its sign-in)

How to make each registration: docs/SETUP.md "Meeting services". Then Connect in Settings → Calendar.
Prints only whether something is set up – never an id, secret or password.
"""
import getpass
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'setup'))
import oauth_flow as O  # noqa: E402
import calendar_invites as CI  # noqa: E402

kc = O.Keychain()


def ask(label, secret=False, pattern=None, default=None):
    while True:
        v = (getpass.getpass if secret else input)('%s%s: ' % (label, ' [%s]' % default if default else '')).strip() or (default or '')
        if v and (not pattern or re.match(pattern, v)):
            return v
        print('  that doesn\'t look right – try again (Ctrl-C to stop)')


def show():
    for k, p in O.PROVIDERS.items():
        st = O.OAuth(kc).status(k)['state']
        print('%-16s %s' % (p['label'], {'not_set_up': 'not set up', 'not_connected': 'set up – Connect it in Settings → Calendar',
                                          'connected': 'connected', 'needs_approval': 'waiting for your IT'}.get(st, st)))
    print('%-16s %s' % ('iCloud invites', 'set up' if CI.CalDav(kc).configured() else 'not set up'))


def main(argv):
    if not argv:
        return show()
    what = argv[0]
    if what == 'remove' and len(argv) > 1:
        name = argv[1]
        if name == 'icloud':
            kc.delete(CI.CALDAV_SERVICE, 'icloud')
        elif name in O.PROVIDERS:
            kc.delete(O.APP_SERVICE, name)
            kc.delete(O.TOKEN_SERVICE, name)
        else:
            sys.exit('unknown: %s' % name)
        print('removed – also remove Axella\'s access on the service\'s own page')
        return
    if what == 'icloud':
        print('iCloud invites: make an app-specific password at https://account.apple.com → Sign-In and Security →\n'
              'App-Specific Passwords, named "Axella invites". It is only used to save events with invitees on iCloud.')
        aid = ask('Apple Account address', pattern=r'^[^@\s]+@[^@\s]+\.[a-z]{2,}$')
        pw = ask('App-specific password (xxxx-xxxx-xxxx-xxxx)', secret=True, pattern=r'^[a-z]{4}-[a-z]{4}-[a-z]{4}-[a-z]{4}$')
        kc.set(CI.CALDAV_SERVICE, 'icloud', {'apple_id': aid, 'password': pw})
        print('saved in the Keychain')
        return
    if what not in O.PROVIDERS:
        sys.exit('unknown: %s (teams, google_meet, zoom, icloud)' % what)
    app = {'client_id': ask('Client id', pattern=r'^[A-Za-z0-9._-]{8,200}$'),
           'client_secret': ask('Client secret', secret=True, pattern=r'^\S{8,300}$')}
    if what == 'teams':
        app['tenant'] = ask('Tenant (organizations, or your work tenant id)', default='organizations',
                            pattern=r'^(organizations|common|[0-9a-f-]{36}|[a-z0-9.-]+\.[a-z]{2,})$')
    kc.set(O.APP_SERVICE, what, app)
    print('saved in the Keychain – now Connect %s in Settings → Calendar → Meeting services' % O.PROVIDERS[what]['label'])


if __name__ == '__main__':
    try:
        main(sys.argv[1:])
    except KeyboardInterrupt:
        print('\nstopped – nothing changed')
    except O.Bad as e:
        sys.exit(str(e))
