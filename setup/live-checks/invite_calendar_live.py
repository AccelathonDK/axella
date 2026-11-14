#!/usr/bin/env python3
"""LIVE check of answering invitations in Calendar itself (calendar_answer.py) – run on the Mac mini, in Terminal:

    cd ~/dev/own/home-server/axella && /usr/bin/python3 setup/live-checks/invite_calendar_live.py "<meeting title>"

1. compiles the AppleScript (a syntax slip shows here, not in the middle of an answer);
2. checks that Accessibility is allowed for the program running it (Terminal here; the action service needs it for
   its own Python – System Settings → Privacy & Security → Accessibility);
3. looks for that invitation under Calendar's "New" WITHOUT pressing anything, and prints only counts
   ("1 matching row of 3") – no other invitation's title, organizer or time.

Only with --answer accepted|tentative|declined, and after you type "yes", it presses that answer – the same as
clicking it in Calendar yourself – and prints the outcome word. Use a test invitation (e.g. one you send yourself from
another calendar), or a real one you want to answer anyway.

Run it three ways before trusting it: with your user on screen, with the screen locked (start it, lock within the
countdown), and with another macOS user on screen (fast user switching) – the last is the least certain.
The first run may ask to let Terminal control System Events and Calendar: allow it. Exit code 0 = all steps passed.
Python 3.9.
"""
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import calendar_answer as C  # noqa: E402


def osa(script, *args, timeout=60):
    p = subprocess.run(['/usr/bin/osascript', '-e', script, *[str(a) for a in args]], capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout).strip() or 'AppleScript failed')
    return p.stdout.strip()


def main():
    args = sys.argv[1:]
    answer = None
    if '--answer' in args:
        i = args.index('--answer')
        answer = args[i + 1] if i + 1 < len(args) else ''
        del args[i:i + 2]
        if answer not in C.BUTTON:
            sys.exit('--answer accepted | tentative | declined')
    delay = 0
    if '--wait' in args:                      # e.g. --wait 20: time to lock the screen or switch user first
        i = args.index('--wait')
        delay = int(args[i + 1])
        del args[i:i + 2]
    if not args:
        sys.exit(__doc__.split('\n\n')[1])
    title, organizer = args[0], (args[1] if len(args) > 1 else '')
    ok = True

    out = os.path.join(tempfile.mkdtemp(prefix='ax-live-'), 'check.scpt')
    p = subprocess.run(['/usr/bin/osacompile', '-o', out, '-e', C.SCRIPT], capture_output=True, text=True)
    print(('  ok   ' if p.returncode == 0 else '  FAIL ') + 'the AppleScript compiles' + ('' if p.returncode == 0 else ': ' + p.stderr.strip()[:300]))
    if p.returncode != 0:
        return 1

    if delay:
        print('  …    waiting %d s – lock the screen or switch user now' % delay)
        time.sleep(delay)
    try:
        ax = osa('tell application "System Events" to return UI elements enabled', timeout=15) == 'true'
    except Exception as e:
        ax = False
        print('         (%s)' % str(e)[:160])
    print(('  ok   ' if ax else '  FAIL ') + 'Accessibility allowed for this program')
    if not ax:
        return 1

    r = C.look(osa, title, organizer)
    if r.startswith('found:'):
        n, rows = r[6:].split('/')
        print('  ok   ' + 'Calendar reached: %s matching row%s of %s under New' % (n, '' if n == '1' else 's', rows))
        ok = n == '1' or answer is None
        if n != '1':
            print('         ' + ('not under New – Axella would answer by mail (or say it is already answered)' if n == '0'
                                 else 'more than one match – Axella would answer nothing and say so'))
    else:
        print('  FAIL ' + "Calendar not reached: %s (%s)" % (r, C.REASONS.get(r, '?')))
        return 1

    if answer and ok:
        if input('Press %s on "%s" in Calendar now? Type yes: ' % (answer, title)).strip().lower() != 'yes':
            print('  –    not pressed')
            return 0
        r = C.answer(osa, title, organizer, '', answer)
        print(('  ok   ' if r == C.OK else '  FAIL ') + 'answer: %s%s' % (r, '' if r == C.OK else ' – ' + C.REASONS.get(r, '?')))
        ok = r == C.OK
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
