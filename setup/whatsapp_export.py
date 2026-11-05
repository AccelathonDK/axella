#!/usr/bin/env python3
"""Read WhatsApp Desktop's local database (read-only copy) and write a short summary for Axella runs.

Why: the Mac mini locks after 1 minute, and a locked Mac hides every app window, so WhatsApp can't be read from
its UI. The database can – and reading it never opens a chat or marks anything as read on the phone.

Output: state/whatsapp.json (chmod 600, not in git) –
  {"generated", "ok", "error", "window_hours", "chats": [{"jid", "phone", "name", "group", "unread", "archived",
    "last_at", "last_from_me", "messages": [{"at", "from_me", "sender", "text"}]}]}
Only chats with activity in the last WINDOW_HOURS are included, newest first, at most MAX_MSGS messages each.

Needs Full Disk Access for the Python that runs it (macOS protects other apps' data).
Test from Terminal:  /usr/bin/python3 setup/whatsapp_export.py --print
"""
import datetime
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile

WA_DIR = os.path.expanduser('~/Library/Group Containers/group.net.whatsapp.WhatsApp.shared')
DB = 'ChatStorage.sqlite'
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), 'state', 'whatsapp.json')
WINDOW_HOURS = 48
MAX_CHATS = 60
MAX_MSGS = 25
MAX_TEXT = 1000
EPOCH = datetime.datetime(2001, 1, 1, tzinfo=datetime.timezone.utc)   # Core Data timestamps
MEDIA = {1: '[photo]', 2: '[video]', 3: '[voice message]', 4: '[contact]', 5: '[location]', 7: '[link]',
         8: '[document]', 11: '[GIF]', 15: '[sticker]'}


def ts(v):
    if v is None:
        return None
    return (EPOCH + datetime.timedelta(seconds=float(v))).astimezone().isoformat(timespec='seconds')


def cols(con, table):
    return {r[1] for r in con.execute(f'PRAGMA table_info({table})')}


def clean(name):
    """Unsaved contacts come as '\u202a+41 79 …\u202c' – drop direction marks and odd spaces."""
    if not name:
        return name
    for ch in ('\u202a', '\u202c', '\u200e', '\u200f'):
        name = name.replace(ch, '')
    return name.replace('\xa0', ' ').strip()


B64ISH = re.compile(r'^[A-Za-z0-9+/_-]{12,}={0,2}$')


def name_ok(s):
    """A display name, or None for empty values and encoded blobs (long runs without spaces, base64-looking)."""
    s = clean(s if isinstance(s, str) else None)
    if not s or B64ISH.match(s) or len(s) > 80:
        return None
    return s


IMAGE_EXT = ('.jpg', '.jpeg', '.png', '.webp', '.gif', '.heic')


def media_file(rel):
    """Absolute path of a downloaded photo inside WhatsApp's own folder, or None (missing, not an image, or outside)."""
    if not rel or not isinstance(rel, str):
        return None
    root = os.path.realpath(WA_DIR)
    for base in (os.path.join(WA_DIR, 'Message'), WA_DIR):
        p = os.path.realpath(os.path.join(base, rel.lstrip('/')))
        if p.startswith(root + os.sep) and p.lower().endswith(IMAGE_EXT) and os.path.isfile(p):
            return p
    return None


def phone(jid):
    if jid and jid.endswith('@s.whatsapp.net'):
        return '+' + jid.split('@')[0]
    return None


def export():
    tmp = tempfile.mkdtemp(prefix='axella-wa-')
    try:
        for ext in ('', '-wal', '-shm'):
            src = os.path.join(WA_DIR, DB + ext)
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(tmp, DB + ext))
        con = sqlite3.connect(os.path.join(tmp, DB))
        con.row_factory = sqlite3.Row
        sc, mc = cols(con, 'ZWACHATSESSION'), cols(con, 'ZWAMESSAGE')
        gm = cols(con, 'ZWAGROUPMEMBER') if con.execute(
            "select 1 from sqlite_master where name='ZWAGROUPMEMBER'").fetchone() else set()
        since = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=WINDOW_HOURS) - EPOCH).total_seconds()

        pick = lambda c, have: c if c in have else 'NULL'
        chats = con.execute(f'''
            select Z_PK pk, {pick('ZCONTACTJID', sc)} jid, {pick('ZPARTNERNAME', sc)} name,
                   {pick('ZSESSIONTYPE', sc)} stype, {pick('ZUNREADCOUNT', sc)} unread,
                   {pick('ZARCHIVED', sc)} archived, {pick('ZLASTMESSAGEDATE', sc)} last
            from ZWACHATSESSION where {pick('ZLASTMESSAGEDATE', sc)} >= ?
            order by last desc limit ?''', (since, MAX_CHATS)).fetchall()

        has = lambda t: bool(con.execute("select 1 from sqlite_master where type='table' and name=?", (t,)).fetchone())
        # who wrote a group message: the member's contact name, else their WhatsApp profile name, else their number.
        # (ZWAMESSAGE.ZPUSHNAME is an encoded blob in current WhatsApp versions – never shown as a name.)
        sender_join, member_name, member_jid = '', 'NULL', 'NULL'
        if 'ZGROUPMEMBER' in mc and has('ZWAGROUPMEMBER'):
            sender_join = 'left join ZWAGROUPMEMBER g on g.Z_PK = m.ZGROUPMEMBER'
            member_name = 'g.ZCONTACTNAME' if 'ZCONTACTNAME' in gm else 'NULL'
            member_jid = 'g.ZMEMBERJID' if 'ZMEMBERJID' in gm else 'NULL'
        pp = cols(con, 'ZWAPROFILEPUSHNAME') if has('ZWAPROFILEPUSHNAME') else set()
        profile_name = 'NULL'
        if {'ZJID', 'ZPUSHNAME'} <= pp and member_jid != 'NULL':
            sender_join += ' left join ZWAPROFILEPUSHNAME pn on pn.ZJID = ' + member_jid
            profile_name = 'pn.ZPUSHNAME'
        # photos already downloaded on this Mac (WhatsApp keeps them under Message/Media/…)
        mi = cols(con, 'ZWAMEDIAITEM') if has('ZWAMEDIAITEM') else set()
        media_join, media_path, thumb_path = '', 'NULL', 'NULL'
        if 'ZMEDIAITEM' in mc and mi:
            media_join = 'left join ZWAMEDIAITEM mi on mi.Z_PK = m.ZMEDIAITEM'
            media_path = 'mi.ZMEDIALOCALPATH' if 'ZMEDIALOCALPATH' in mi else 'NULL'
            thumb_path = 'mi.ZTHUMBNAILLOCALPATH' if 'ZTHUMBNAILLOCALPATH' in mi else 'NULL'
        schema = {'ZWAMESSAGE': sorted(mc), 'ZWAGROUPMEMBER': sorted(gm), 'ZWAPROFILEPUSHNAME': sorted(pp),
                  'ZWAMEDIAITEM': sorted(mi)}           # column names only – to adapt when WhatsApp changes its database

        out = []
        for c in chats:
            msgs = con.execute(f'''
                select m.Z_PK pk, m.ZMESSAGEDATE at, m.ZISFROMME me, m.{pick('ZTEXT', mc)} text,
                       m.{pick('ZMESSAGETYPE', mc)} mtype, {member_name} mname, {profile_name} pname, {member_jid} mjid,
                       {media_path} mpath, {thumb_path} tpath
                from ZWAMESSAGE m {sender_join} {media_join}
                where m.ZCHATSESSION = ? and m.ZMESSAGEDATE >= ?
                order by m.ZMESSAGEDATE desc limit ?''', (c['pk'], since, MAX_MSGS)).fetchall()
            if (c['jid'] or '').endswith(('status@broadcast', '.status')):
                continue                      # Status updates (stories), not chats
            if not msgs and not clean(c['name']):
                continue                      # empty system/status sessions
            is_group = bool(c['jid'] and c['jid'].endswith('@g.us')) or c['stype'] == 1
            chat_name = clean(c['name'])

            def who(m):
                if m['me']:
                    return None
                if not is_group:
                    return chat_name
                return name_ok(m['mname']) or name_ok(m['pname']) or phone(m['mjid']) or None

            def media(m):
                if m['mtype'] not in (1, 11, 15):             # photo, GIF, sticker
                    return None
                for rel in (m['mpath'], m['tpath']):
                    p = media_file(rel)
                    if p:
                        return {'id': m['pk'], 'path': p, 'thumb': rel == m['tpath']}
                return None

            out.append({
                'jid': c['jid'], 'phone': phone(c['jid']), 'name': chat_name, 'group': is_group,
                'unread': c['unread'] or 0, 'archived': bool(c['archived']), 'last_at': ts(c['last']),
                'last_from_me': bool(msgs[0]['me']) if msgs else None,
                'messages': [{
                    'at': ts(m['at']), 'from_me': bool(m['me']), 'sender': who(m),
                    'text': (m['text'] or MEDIA.get(m['mtype'], '[message]'))[:MAX_TEXT],
                    **({'media': media(m)} if media(m) else {}),
                } for m in reversed(msgs)],
            })
        con.close()
        return {'ok': True, 'error': None, 'window_hours': WINDOW_HOURS, 'schema': schema, 'chats': out}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def split_private(chats):
    """Private contacts (setup/privacy.py): their chats never go into whatsapp.json, which Claude runs read.
    'private' chats become a count on the dashboard's Private card – no text, no media, no group members;
    'hidden' chats are left out completely. Group chats are matched on the group id."""
    import privacy
    pv = privacy.Privacy(os.path.dirname(OUT))
    keep, private = [], []
    for c in chats:
        lvl = pv.level('whatsapp', c.get('jid'))
        if lvl == 'normal':
            keep.append(c)
            continue
        if lvl == 'hidden':
            continue
        who = pv.contact(c.get('jid'))
        msgs = c.get('messages') or []
        theirs = 0                                   # messages from them since your last one
        for m in reversed(msgs):
            if m.get('from_me'):
                break
            theirs += 1
        private.append({'channel': 'whatsapp', 'contact': who['id'] if who else None,
                        'name': (who or {}).get('name') or c.get('name') or 'Private chat', 'group': bool(c.get('group')),
                        'unread': c.get('unread') or 0, 'waiting': theirs, 'last_at': c.get('last_at'),
                        'last_from_me': c.get('last_from_me'), 'open': ('whatsapp://send?phone=' + c['phone'].lstrip('+'))
                        if c.get('phone') else 'whatsapp://'})
    return keep, private


_PRIVATE_LOCK = __import__('threading').Lock()      # WhatsApp, Signal and Mail/iMessage write here from their own threads


def write_private(channel, rows, at):
    """state/private-inbox.json – one list per platform; read only by the action service (never by a Claude run)."""
    with _PRIVATE_LOCK:
        _write_private(channel, rows, at)


def _write_private(channel, rows, at):
    path = os.path.join(os.path.dirname(OUT), 'private-inbox.json')
    try:
        with open(path, encoding='utf-8') as f:
            d = json.load(f)
    except (OSError, ValueError):
        d = {}
    d[channel] = {'at': at, 'chats': rows}
    tmp = '%s.%d.%s.tmp' % (path, os.getpid(), channel)       # own temp file per writer: a second process can't take it away
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def write():
    import privacy
    if privacy.Privacy(os.path.dirname(OUT)).broken():
        # privacy.json can't be read: nothing new is written – the last export stays, and goes stale (System status)
        return {'ok': False, 'chats': [], 'error': 'privacy settings can\'t be read – nothing exported until they are fixed',
                'generated': datetime.datetime.now().astimezone().isoformat(timespec='seconds')}
    try:
        data = export()
    except PermissionError:
        data = {'ok': False, 'chats': [], 'error': 'No access to WhatsApp data – give Full Disk Access to the Python '
                'that runs the Axella action service (see README).'}
    except Exception as e:  # schema change, WhatsApp not installed, …
        data = {'ok': False, 'chats': [], 'error': f'{type(e).__name__}: {str(e)[:300]}'}
    data['generated'] = datetime.datetime.now().astimezone().isoformat(timespec='seconds')
    data['chats'], private = split_private(data.get('chats') or [])
    write_private('whatsapp', private, data['generated'])
    tmp = OUT + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.chmod(tmp, 0o600)
    os.replace(tmp, OUT)
    return data


def run(log=sys.stderr, every=120):
    import time
    while True:
        try:                                            # one bad round must never stop the export for good
            d = write()
            if not d['ok']:
                log.write(f"{d['generated']} whatsapp export: {d['error']}\n")
        except Exception as e:
            log.write('whatsapp export: %s: %s\n' % (type(e).__name__, str(e)[:300]))
        time.sleep(every)


if __name__ == '__main__':
    d = write()
    if '--print' in sys.argv:
        print('ok:', d['ok'], '| error:', d['error'], '| chats in last', WINDOW_HOURS, 'h:', len(d['chats']))
        for c in d['chats'][:8]:   # names and counts only – no message text on screen
            print(f"  {c['last_at']}  {'group ' if c['group'] else ''}{c['name']!r:30} unread={c['unread']} msgs={len(c['messages'])}")
