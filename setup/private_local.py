"""The Private card for Mail and iMessage: who wrote, how many, when – read straight from Mail's index and the
Messages database on this Mac (read-only), never through Claude. Every 2 minutes, last 48 hours, only for contacts
whose Mail / iMessage level is "private" (hidden ones are left out completely). No subject, no text is read.
Writes the 'mail' and 'imessage' parts of state/private-inbox.json (see whatsapp_export.write_private).
"""
import datetime
import os
import sqlite3
import sys
import time
from urllib.parse import quote

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(os.path.dirname(HERE), 'state')
CHAT_DB = os.path.expanduser('~/Library/Messages/chat.db')
WINDOW = 48 * 3600
APPLE_EPOCH = 978307200


def _iso(ts):
    return datetime.datetime.fromtimestamp(ts).astimezone().isoformat(timespec='seconds')


def _ro(path):
    return sqlite3.connect('file:%s?mode=ro' % quote(path), uri=True, timeout=5)


def imessage(pv):
    rows = {}
    if not os.path.exists(CHAT_DB):
        return []
    db = _ro(CHAT_DB)
    try:
        since = time.time() - WINDOW - APPLE_EPOCH
        q = db.execute('''select h.id, m.is_from_me, m.is_read, m.date from message m join handle h on h.ROWID = m.handle_id
                          where m.date > ? order by m.date''', (int(since * 1e9),)).fetchall()
        if not q:                                       # older macOS: seconds instead of nanoseconds
            q = db.execute('''select h.id, m.is_from_me, m.is_read, m.date from message m join handle h on h.ROWID = m.handle_id
                              where m.date > ? order by m.date''', (int(since),)).fetchall()
    finally:
        db.close()
    for handle, me, read, date in q:
        if pv.level('imessage', handle) != 'private':
            continue
        c = pv.contact(handle)
        key = c['id'] if c else handle
        ts = (date / 1e9 if date > 1e12 else date) + APPLE_EPOCH
        r = rows.setdefault(key, {'channel': 'imessage', 'contact': c['id'] if c else None, 'name': (c or {}).get('name') or handle,
                                  'group': False, 'unread': 0, 'waiting': 0, 'last_at': None, 'last_from_me': None,
                                  'open': 'sms:' + handle})
        r['last_at'], r['last_from_me'] = _iso(ts), bool(me)
        if me:
            r['waiting'] = 0
        else:
            r['waiting'] += 1
            r['unread'] += 0 if read else 1
    return list(rows.values())


def mail(pv):
    import mailsearch
    path = mailsearch._envelope()
    if not path:
        return []
    d = pv.load()
    want = {}
    for c in d['contacts']:
        if pv.level('mail', (c.get('ids') or [''])[0]) != 'private':
            continue
        for i in c.get('ids') or []:
            if '@' in i:
                want[i.strip().lower()] = c
    if not want:
        return []
    db = _ro(path)
    try:
        mc = mailsearch._cols(db, 'messages')
        read = 'm.read' if 'read' in mc else ('(m.flags & 1)' if 'flags' in mc else '0')
        gd = mailsearch._cols(db, 'message_global_data') if db.execute(
            "select 1 from sqlite_master where name='message_global_data'").fetchone() else set()
        mid, join = ("g.message_id_header", 'left join message_global_data g on g.ROWID = m.global_message_id') \
            if 'message_id_header' in gd and 'global_message_id' in mc else ('NULL', '')
        marks = ','.join('?' * len(want))
        q = db.execute('''select lower(a.address), %s, m.date_received, %s from messages m join addresses a on a.ROWID = m.sender %s
                          where lower(a.address) in (%s) and m.date_received > ? %s order by m.date_received'''
                       % (read, mid, join, marks, 'and m.deleted = 0' if 'deleted' in mc else ''),
                       list(want) + [int(time.time() - WINDOW)]).fetchall()
    finally:
        db.close()
    rows = {}
    for addr, is_read, ts, msgid in q:
        c = want[addr]
        r = rows.setdefault(c['id'], {'channel': 'mail', 'contact': c['id'], 'name': c['name'], 'group': False, 'unread': 0,
                                      'waiting': 0, 'last_at': None, 'last_from_me': False, 'open': 'message://'})
        r['last_at'] = _iso(ts)
        r['waiting'] += 1
        r['unread'] += 0 if is_read else 1
        if msgid:
            r['open'] = 'message://' + quote('<%s>' % msgid.strip().strip('<>'), safe='')
    return list(rows.values())


def write():
    sys.path.insert(0, HERE)
    import privacy
    import whatsapp_export
    pv = privacy.Privacy(STATE)
    now = datetime.datetime.now().astimezone().isoformat(timespec='seconds')
    if pv.broken():                                     # privacy.json can't be read: nothing new on the Private card
        return
    for ch, fn in (('imessage', imessage), ('mail', mail)):
        try:
            whatsapp_export.write_private(ch, fn(pv), now)
        except Exception as e:                          # e.g. no Full Disk Access – the card just shows nothing
            sys.stderr.write('%s private %s: %s\n' % (now, ch, str(e)[:200]))


def run(every=120):
    while True:
        try:
            write()
        except Exception as e:                          # never let one bad round stop the card for good
            sys.stderr.write('private card: %s\n' % str(e)[:200])
        time.sleep(every)
