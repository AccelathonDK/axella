"""Birthdays (feature pack Nov 2026 §2c): read from macOS Contacts with the address book (contacts_book.py), editable
on Axella's contact card – it stays in one place, Apple Contacts.

Whose: your Favourites (the VIPs) and your keep-in-touch people (people.py) by default, plus anyone you switch "Show
birthday" on for; either can be switched off. Never a private or hidden contact.
How: one discreet line in the morning digest on the day ("Robin's birthday today"). The Mac mini writes
state/birthdays-today.json for that run – first names (and the age when the year is known), nothing else – and
AXELLA.md "Birthdays" tells the run what to do with it. No reminders, no greetings written for you.

state/birthdays.json: {"show": {"<contact id>": true|false}}  – your switches (a missing id: Favourite = on)
Python 3.9.
"""
import datetime
import json
import os
import re
import threading

LOCK = threading.Lock()
BDAY_RE = re.compile(r'^(?:(\d{4})|-)-(\d{2})-(\d{2})$')       # 1984-03-07, or --03-07 without a year


def norm(raw):
    """Contacts' "Y-M-D" (year 1604 = no year) → 'YYYY-MM-DD' or '--MM-DD'; anything else → ''."""
    m = re.match(r'^\s*(\d{1,4})-(\d{1,2})-(\d{1,2})\s*$', str(raw or ''))
    if not m:
        m2 = BDAY_RE.match(str(raw or '').strip())
        return str(raw).strip() if m2 and _valid(None if not m2.group(1) else int(m2.group(1)), int(m2.group(2)), int(m2.group(3))) else ''
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if not _valid(y if y >= 1800 else None, mo, d):
        return ''
    return ('%04d-%02d-%02d' % (y, mo, d)) if y >= 1800 else ('--%02d-%02d' % (mo, d))


def _valid(y, mo, d):
    try:
        datetime.date(y or 2000, mo, d)                         # 2000 is a leap year: 29 Feb without a year is fine
        return True
    except ValueError:
        return False


def parts(bday):
    """'1984-03-07' → (1984, 3, 7); '--03-07' → (None, 3, 7); else None."""
    m = BDAY_RE.match(str(bday or ''))
    if not m:
        return None
    return (int(m.group(1)) if m.group(1) else None), int(m.group(2)), int(m.group(3))


def on_day(bday, day):
    """Is day this birthday? 29 February is kept on 28 February in other years."""
    p = parts(bday)
    if not p:
        return False
    _, mo, d = p
    if (mo, d) == (day.month, day.day):
        return True
    leap = day.year % 4 == 0 and (day.year % 100 != 0 or day.year % 400 == 0)
    return (mo, d) == (2, 29) and not leap and (day.month, day.day) == (2, 28)


def first_name(p):
    return (p.get('first') or str(p.get('name') or '').split(' ')[0] or p.get('company') or '').strip()[:60]


class Birthdays:
    def __init__(self, state_dir):
        self.file = os.path.join(state_dir, 'birthdays.json')
        self.today_file = os.path.join(state_dir, 'birthdays-today.json')
        self.keep = lambda: set()                    # keep-in-touch person ids (set by axella-actions.py from people.py)

    def settings(self):
        try:
            with open(self.file, encoding='utf-8') as f:
                d = json.load(f)
            return d if isinstance(d, dict) and isinstance(d.get('show'), dict) else {'show': {}}
        except (OSError, ValueError):
            return {'show': {}}

    def set_show(self, cid, on):
        cid = str(cid or '')[:120]
        if not cid:
            raise ValueError('unknown contact')
        with LOCK:
            d = self.settings()
            d['show'][cid] = bool(on)
            tmp = self.file + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(d, f)
            os.replace(tmp, self.file)
        return d

    def shown(self, p, settings=None):
        """Does this person's birthday show? Your switch wins; without one, Favourites (VIPs) and keep-in-touch people do."""
        s = (settings or self.settings())['show']
        if p.get('private'):
            return False
        if p.get('id') in s:
            return bool(s[p['id']])
        if p.get('vip'):
            return True
        try:
            return bool(p.get('id')) and p['id'] in self.keep()
        except Exception:
            return False

    def due(self, people, day, settings=None):
        """[{name, turns}] whose birthday is on day (first names; the age only when the year is known)."""
        settings = settings or self.settings()
        out = []
        for p in people or []:
            b = p.get('birthday')
            if not b or not self.shown(p, settings) or not on_day(b, day):
                continue
            y = parts(b)[0]
            nm = first_name(p)
            if nm and nm not in [x['name'] for x in out]:
                out.append({'name': nm, 'turns': (day.year - y) if y and 0 < day.year - y < 120 else None})
        return sorted(out, key=lambda x: x['name'].lower())

    def write_today(self, people, day=None):
        """state/birthdays-today.json for the morning digest – only what it needs, rewritten when it changes."""
        day = day or datetime.date.today()
        data = {'date': day.isoformat(), 'people': self.due(people, day)}
        try:
            with open(self.today_file, encoding='utf-8') as f:
                if json.load(f) == data:
                    return data
        except (OSError, ValueError):
            pass
        tmp = self.today_file + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, self.today_file)
        return data
