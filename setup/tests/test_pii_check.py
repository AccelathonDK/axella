#!/usr/bin/env python3
"""tools/pii-check.py – the real-data check. Everything here is invented: a made-up owner's data in a temp folder, and
made-up files that copy a value from it. Run: python3 setup/tests/test_pii_check.py"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CHECK = os.path.join(HERE, 'tools', 'pii-check.py')

fails = 0


def ok(c, label):
    global fails
    print(('  ok   ' if c else '  FAIL ') + label)
    fails += 0 if c else 1


if not shutil.which('git'):
    print('SKIP – git not installed')
    sys.exit(0)

tmp = tempfile.mkdtemp(prefix='axpii-')
repo, state, local = os.path.join(tmp, 'repo'), os.path.join(tmp, 'state'), os.path.join(tmp, 'local')
for d in (repo, state, local, os.path.join(repo, 'setup', 'tests')):
    os.makedirs(d, exist_ok=True)

# the invented owner's data
REF, TRAVELLER, PLACE, SENDER = 'QZX7KW', 'Robin Quillfeather', 'Zorbaville', 'tickets@zorbair.example'
json.dump({'trips': [{'name': 'Away', 'bookings': [{'ref': REF, 'travellers': [TRAVELLER], 'place': PLACE,
                                                     'from': SENDER, 'notes': 'Ticket 999-7310452866'}]}]},
          open(os.path.join(state, 'trips.json'), 'w'))
json.dump({'people': [{'first': 'Kim', 'last': 'Vantablack', 'emails': ['kim.v@mail.example'], 'phones': ['+45 71 92 83 64']}]},
          open(os.path.join(state, 'contacts-book.json'), 'w'))
config = os.path.join(tmp, 'actions-config.json')
json.dump({'owner': {'name': 'Alex Example'}, 'workplaces': [{'name': 'Grommet Works', 'domains': ['grommet.example']}]},
          open(config, 'w'))
open(os.path.join(local, 'blocklist.txt'), 'w').write('# general\n[a-z0-9-]+\\.tail[0-9a-f]+\\.ts\\.net\n')
open(os.path.join(local, 'blocklist.local.txt'), 'w').write('# local\nmoonfern\n')

env = dict(os.environ, AXELLA_PII_STATE=state, AXELLA_PII_CONFIG=config, AXELLA_PII_LOCAL=local)


def git(*a):
    subprocess.run(['git', '-c', 'user.name=t', '-c', 'user.email=t@example.com'] + list(a), cwd=repo,
                   capture_output=True, text=True)


def run(*args, e=None):
    r = subprocess.run([sys.executable, CHECK, '--test'] + list(args), cwd=repo, capture_output=True, text=True, env=e or env)
    return r.returncode, r.stdout + r.stderr


def write(path, text):
    p = os.path.join(repo, path)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, 'w').write(text)


git('init', '-q')
write('setup/clean.py', '# a clean file\nx = "Lee Chen <lee@example.com>"  # 2027-03-20 10:30, ref 5550003333\n')
code, out = run('--tree')
ok(code == 0, 'a clean tree passes')

# each kind of copied value is caught, and the value itself is never printed
cases = [('booking reference', REF), ('traveller', TRAVELLER), ('place', PLACE), ('sender', SENDER),
         ('ticket number', '999-7310452866'), ('contact name', 'Kim Vantablack'), ('phone number', '71 92 83 64'),
         ('workplace', 'Grommet Works'), ('blocklist', 'moonfern')]
for kind, secret in cases:
    write('setup/leak.py', 'note = "seen: %s, then home"\n' % secret)
    code, out = run('--tree')
    ok(code == 1 and kind in out, 'caught: %s' % kind)
    ok(secret.lower() not in out.lower(), 'not printed: %s' % kind)
os.remove(os.path.join(repo, 'setup', 'leak.py'))

write('setup/word.py', 'zorbavilleish = 1\n')
ok(run('--tree')[0] == 0, 'a value inside a longer word is not a hit')
os.remove(os.path.join(repo, 'setup', 'word.py'))

# pattern check: e-mail domains and long numbers in tests
write('setup/tests/test_x.py', 'a = "someone@realmail.dk"\n')
code, out = run('--tree')
ok(code == 1 and 'e-mail address outside the made-up domains' in out, 'a real-looking e-mail address is caught')
write('setup/tests/test_x.py', 'n = "7310 4528 66"\n')
code, out = run('--tree')
ok(code == 1 and 'does not look made up' in out, 'a real-looking long number in a test is caught')
write('setup/tests/test_x.py', 'n = "5550003333"; m = "45 00 00 00 07"; d = "2027-03-20T10:30:00"; e = "x@example-town.dk"\n')
ok(run('--tree')[0] == 0, 'made-up numbers, dates, times and example- domains pass')
os.remove(os.path.join(repo, 'setup', 'tests', 'test_x.py'))

# --staged: only the lines a commit adds
git('add', '-A'); git('commit', '-q', '-m', 'base')
write('setup/clean.py', open(os.path.join(repo, 'setup', 'clean.py')).read() + 'y = "%s"\n' % REF)
git('add', '-A')
code, out = run('--staged')
ok(code == 1 and 'setup/clean.py:3' in out and REF.lower() not in out.lower(), '--staged catches an added line, with path:line')
git('reset', '-q', '--hard')

# --dir: a built copy
pub = os.path.join(tmp, 'pub')
os.makedirs(pub)
open(os.path.join(pub, 'README.md'), 'w').write('Made by %s.\n' % TRAVELLER)
code, out = run('--dir', pub)
ok(code == 1 and 'README.md:1' in out, '--dir checks a built copy')

# the local allow list: path-bound
open(os.path.join(local, 'pii-allow.local.txt'), 'w').write('# local\nREADME.md\t%s\n' % TRAVELLER.lower())
ok(run('--dir', pub)[0] == 0, 'an allowed value in its own file passes')
open(os.path.join(pub, 'OTHER.md'), 'w').write('%s again\n' % TRAVELLER)
ok(run('--dir', pub)[0] == 1, 'the same value in another file is still caught')
os.remove(os.path.join(local, 'pii-allow.local.txt'))

# it refuses to run weaker
os.rename(os.path.join(local, 'blocklist.local.txt'), os.path.join(local, 'gone.txt'))
ok(run('--tree')[0] == 2, 'refuses (exit 2) without the local blocklist')
os.rename(os.path.join(local, 'gone.txt'), os.path.join(local, 'blocklist.local.txt'))
ok(run('--tree', e=dict(env, AXELLA_PII_STATE=os.path.join(tmp, 'nowhere')))[0] == 2, 'refuses (exit 2) without the data')

# without --test the variables are ignored: the real data in this repo is used, by the check and by release-check
empty = os.path.join(tmp, 'empty')
os.makedirs(empty)
fake = dict(os.environ, AXELLA_PII_STATE=empty, AXELLA_PII_CONFIG=os.path.join(empty, 'none.json'), AXELLA_PII_LOCAL=empty)
if os.path.exists(os.path.join(HERE, 'state', 'trips.json')) and os.path.exists(os.path.join(HERE, 'setup', 'actions-config.json')):
    r = subprocess.run([sys.executable, CHECK, '--tree'], cwd=HERE, capture_output=True, text=True, env=fake)
    ok(r.returncode != 2 and ('values from your data' in r.stdout or 'real data found' in r.stdout),
       'pii-check without --test ignores the variables and loads the real data')
    r = subprocess.run(['bash', os.path.join(HERE, 'tools', 'release-check.sh'), '--tree'], cwd=HERE, capture_output=True,
                       text=True, env=fake)
    ok('could not run' not in r.stdout and ('values from your data' in r.stdout or 'real data found' in r.stdout),
       'release-check --tree still loads the real data when the variables point at an empty folder')
else:
    print('  skip  real-data checks (no state/ here – run on the Mac mini)')

shutil.rmtree(tmp, ignore_errors=True)
print('%d failed' % fails if fails else 'all passed')
sys.exit(1 if fails else 0)
