"""Search all mail on this Mac and read a found message – read-only, Mail itself isn't touched.

Two sources, merged:
  1. Mail's own index (~/Library/Mail/V*/MailData/Envelope Index, SQLite, opened read-only): every message Mail knows,
     with sender, recipients, subject, date and folder – years of mail in well under a second.
  2. Spotlight (mdfind) for words in the text, where macOS still indexes Mail's files (newer macOS versions often
     don't – then this part just finds nothing).
A found message is read straight from its .emlx file (headers, plain text, attachments). If Mail hasn't downloaded
it, the action service falls back to reading it through Mail (AppleScript). Replying goes through the normal reply
path (AppleScript, by account + message id).

The browser never sees or sends a file path: each result gets a random token that maps to what's needed here, in
memory, for the last searches only. Needs Full Disk Access for the Python that runs the action service (it already
has it for WhatsApp).
"""
import email
import email.header
import email.policy
import email.utils
import glob
import html
import os
import re
import secrets
import sqlite3
import subprocess
import datetime
from email.parser import BytesHeaderParser, BytesParser
from urllib.parse import quote, unquote, urlparse

MAIL_DIR = os.path.expanduser('~/Library/Mail')
MAX_TOKENS = 600
_TOK = {}                                   # token -> {'path', 'account', 'mid', 'rowid', 'base'} (oldest dropped)
WORD = re.compile(r'[^\w@.+\-]', re.UNICODE)


class SearchError(Exception):
    pass


class NotDownloaded(SearchError):
    def __init__(self, account, mid):
        super().__init__("Mail hasn't downloaded this message")
        self.account, self.mid = account, mid


def _words(q):
    out = []
    for w in str(q or '').split():
        w = WORD.sub('', w)[:60]
        if len(w) >= 2:
            out.append(w)
    return out[:8]


def _dec(v):
    try:
        return str(email.header.make_header(email.header.decode_header(v or ''))).strip()
    except Exception:
        return str(v or '').strip()


def _iso_ts(t):
    try:
        return datetime.datetime.fromtimestamp(float(t)).astimezone().isoformat(timespec='minutes')
    except Exception:
        return None


def _iso(d):
    try:
        return email.utils.parsedate_to_datetime(d).astimezone().isoformat(timespec='minutes')
    except Exception:
        return None


def _inside(p):
    root = os.path.realpath(MAIL_DIR)
    rp = os.path.realpath(p)
    return rp if rp.startswith(root + os.sep) and rp.endswith('.emlx') and os.path.isfile(rp) else None


def _raw(path, headers_only=False):
    """The RFC 822 message inside an .emlx file (first line: byte count, then the message, then a plist)."""
    with open(path, 'rb') as f:
        first = f.readline()
        try:
            n = int(first.strip())
        except ValueError:
            f.seek(0)
            n = -1
        return f.read(min(n, 65536) if headers_only and n > 0 else n)


TOKEN_TTL = 30 * 60                         # a found mail's link works for half an hour


def _token(entry):
    import time
    tok = secrets.token_urlsafe(12)
    _TOK[tok] = dict(entry, _at=time.time())
    while len(_TOK) > MAX_TOKENS:
        _TOK.pop(next(iter(_TOK)))
    return tok


# ---------- 1. Mail's own index ----------
def _envelope():
    c = sorted(glob.glob(os.path.join(MAIL_DIR, 'V*', 'MailData', 'Envelope Index')),
               key=lambda p: int(re.sub(r'\D', '', p.split(os.sep)[-3]) or 0), reverse=True)
    return c[0] if c else None


def _cols(db, t):
    return {r[1] for r in db.execute('PRAGMA table_info(%s)' % t)}


def _mailbox(url, vdir):
    """('account id', 'INBOX/Sub', '/…/V10/<id>/INBOX.mbox/Sub.mbox') from a mailbox url like imap://<id>/INBOX/Sub"""
    u = urlparse(url or '')
    parts = [unquote(p) for p in u.path.split('/') if p]
    base = os.path.join(vdir, u.netloc, *[p + '.mbox' for p in parts]) if u.netloc else None
    return u.netloc or None, '/'.join(parts), base


def _emlx(base, rowid, deep=False):
    """Mail keeps message <rowid> at <mailbox>/<store id>/Data/<digits of rowid//1000, reversed>/Messages/<rowid>.emlx"""
    if not base:
        return None
    n = int(rowid) // 1000
    sub = os.path.join(*reversed(str(n))) if n else ''
    for name in ('%d.emlx' % rowid, '%d.partial.emlx' % rowid):
        for p in glob.glob(os.path.join(glob.escape(base), '*', 'Data', sub, 'Messages', name)):
            rp = _inside(p)
            if rp:
                return rp
    if deep:                                       # unusual layout: look through the whole mailbox once
        for name in ('%d.emlx' % rowid, '%d.partial.emlx' % rowid):
            for p in glob.iglob(os.path.join(glob.escape(base), '**', name), recursive=True):
                rp = _inside(p)
                if rp:
                    return rp
    return None


def search_index(words, account_names, own, limit, before=None):
    path = _envelope()
    if not path:
        raise SearchError("Mail's index wasn't found (no ~/Library/Mail/V*/MailData/Envelope Index)")
    vdir = os.path.dirname(os.path.dirname(path))
    try:
        db = sqlite3.connect('file:%s?mode=ro' % quote(path), uri=True, timeout=5)
    except sqlite3.Error as e:
        raise SearchError("Mail's index can't be opened: %s" % e)
    try:
        mc = _cols(db, 'messages')
        have = {r[0] for r in db.execute("select name from sqlite_master where type='table'")}
        if not {'subjects', 'addresses', 'mailboxes'} <= have or not {'sender', 'subject', 'mailbox'} <= mc:
            raise SearchError("Mail's index has a layout Axella doesn't know yet")
        gd = _cols(db, 'message_global_data') if 'message_global_data' in have else set()
        g_join = g_col = ''
        if 'global_message_id' in mc and 'message_id_header' in gd:
            g_join, g_col = 'left join message_global_data g on g.ROWID = m.global_message_id', ', g.message_id_header mid'
        rc = _cols(db, 'recipients') if 'recipients' in have else set()
        where, args = [], []
        for w in words:
            like = '%' + w.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
            c = "(s.subject like ? escape '\\' or a.address like ? escape '\\' or a.comment like ? escape '\\'"
            args += [like] * 3
            if {'message', 'address'} <= rc:
                c += (" or exists (select 1 from recipients r join addresses ra on ra.ROWID = r.address"
                      " where r.message = m.ROWID and (ra.address like ? escape '\\' or ra.comment like ? escape '\\'))")
                args += [like] * 2
            where.append(c + ')')
        if 'deleted' in mc:
            where.append('m.deleted = 0')
        date = 'm.date_received' if 'date_received' in mc else ('m.date_sent' if 'date_sent' in mc else 'm.ROWID')
        if before is not None and date != 'm.ROWID':     # "Show older": only mail received before this moment (epoch seconds)
            where.append('%s < ?' % date)
            args.append(float(before))
        prefix = 'm.subject_prefix' if 'subject_prefix' in mc else "''"
        rows = db.execute('''select m.ROWID rowid, %s prefix, s.subject subject, a.address addr, a.comment name, %s date,
                                    mb.url url %s
                             from messages m join subjects s on s.ROWID = m.subject
                             left join addresses a on a.ROWID = m.sender
                             join mailboxes mb on mb.ROWID = m.mailbox %s
                             where %s order by %s desc limit ?''' % (prefix, date, g_col, g_join, ' and '.join(where), date),
                          args + [limit * 3]).fetchall()
        out, seen = [], set()
        for r in rows:
            r = dict(zip(['rowid', 'prefix', 'subject', 'addr', 'name', 'date', 'url'] + (['mid'] if g_col else []), r))
            acc_id, box, base = _mailbox(r['url'], vdir)
            mid = (r.get('mid') or '').strip().strip('<>').strip() or None
            key = mid or ('row', r['rowid'])
            if key in seen:                         # the same mail in two folders
                continue
            seen.add(key)
            p = _emlx(base, r['rowid'])
            if not mid and p:                       # older index without message ids: read the header
                try:
                    h = BytesHeaderParser(policy=email.policy.compat32).parsebytes(_raw(p, headers_only=True))
                    mid = (h.get('Message-ID') or '').strip().strip('<>').strip() or None
                except Exception:
                    pass
            acc = account_names.get(acc_id)
            addr = r['addr'] or ''
            to, rcpt = '', []
            if {'message', 'address'} <= rc:            # every recipient: for the private-contact check, and "You → …"
                t = db.execute('select ra.comment, ra.address from recipients r join addresses ra on ra.ROWID = r.address'
                               ' where r.message = ? limit 50', (r['rowid'],)).fetchall()
                rcpt = [a for _, a in t if a]
                if addr.lower() in own:
                    to = ', '.join((c or a or '') for c, a in t[:3])
            out.append({'token': _token({'path': p, 'account': acc, 'mid': mid, 'rowid': r['rowid'], 'base': base}),
                        'subject': ((r['prefix'] or '') + (r['subject'] or '')).strip() or '(no subject)',
                        'from_name': r['name'] or '', 'from_address': addr, 'from_me': addr.lower() in own, 'to': to,
                        'date': _iso_ts(r['date']), 'message_id': mid, 'account': acc, 'mailbox': box,
                        'has_attachments': _has_att(db, r['rowid']), '_addrs': [addr] + rcpt})
            if len(out) >= limit:
                break
        return out
    finally:
        db.close()


def _has_att(db, rowid):
    """True/False from Mail's own attachments table; None when this index has no such table (then the dashboard asks)."""
    try:
        if 'message' not in _cols(db, 'attachments'):
            return None
        return db.execute('select 1 from attachments where message = ? limit 1', (rowid,)).fetchone() is not None
    except sqlite3.Error:
        return None


def invite_candidates(account_names, days=30, limit=60, now=None):
    """Recent messages that carry a calendar invitation (an .ics attachment, or an invitation subject) – newest first.
    Trash and junk are left out. Only the index is read here; the caller reads and checks each .ics."""
    import time
    path = _envelope()
    if not path:
        return []
    vdir = os.path.dirname(os.path.dirname(path))
    db = sqlite3.connect('file:%s?mode=ro' % quote(path), uri=True, timeout=5)
    try:
        mc = _cols(db, 'messages')
        have = {r[0] for r in db.execute("select name from sqlite_master where type='table'")}
        if not {'subjects', 'addresses', 'mailboxes'} <= have or not {'sender', 'subject', 'mailbox'} <= mc:
            return []
        gd = _cols(db, 'message_global_data') if 'message_global_data' in have else set()
        g_join = g_col = ''
        if 'global_message_id' in mc and 'message_id_header' in gd:
            g_join, g_col = 'left join message_global_data g on g.ROWID = m.global_message_id', ', g.message_id_header mid'
        date = 'm.date_received' if 'date_received' in mc else 'm.date_sent'
        ac = _cols(db, 'attachments') if 'attachments' in have else set()
        cond = ["s.subject like 'Invitation:%'", "s.subject like 'Updated invitation%'", "s.subject like 'Invitation from%'",
                "s.subject like 'Invitation (%'", "s.subject like 'Invitasjon:%'", "s.subject like 'Invitation til%'",
                "s.subject like 'Einladung:%'", "s.subject like 'Uitnodiging:%'"]
        if {'message', 'name'} <= ac:
            cond.append("exists (select 1 from attachments at where at.message = m.ROWID and lower(at.name) like '%.ics')")
        where = '(%s) and %s > ?' % (' or '.join(cond), date)
        if 'deleted' in mc:
            where += ' and m.deleted = 0'
        sql = ('select m.ROWID, s.subject, a.address, a.comment, %s, mb.url %s from messages m'
               ' join subjects s on s.ROWID = m.subject left join addresses a on a.ROWID = m.sender'
               ' join mailboxes mb on mb.ROWID = m.mailbox %s where %s order by %s desc limit ?') % (date, g_col, g_join, where, date)
        rows = db.execute(sql, ((now or time.time()) - days * 86400, limit)).fetchall()
    finally:
        db.close()
    out, seen = [], set()
    for r in rows:
        rowid, subj, addr, name, dt, url = r[:6]
        mid = (r[6] if g_col else '') or ''
        mid = mid.strip().strip('<>').strip() or None
        acc_id, box, base = _mailbox(url, vdir)
        if re.search(r'trash|deleted|junk|spam|papirkurv|uønsket', box or '', re.I) or not account_names.get(acc_id):
            continue
        if mid and mid in seen:
            continue
        p = _emlx(base, rowid)
        if not p:
            continue
        seen.add(mid)
        out.append({'path': p, 'account': account_names.get(acc_id), 'message_id': mid, 'subject': subj or '',
                    'from_name': name or '', 'from_address': addr or '', 'date': _iso_ts(dt), 'mailbox': box})
    return out


def booking_candidates(account_names, match, days=548, limit=400, now=None):
    """Mails that may be booking confirmations (match(subject, sender) says so) from the last `days`, newest first –
    from Mail's index only; Sent, trash and junk left out. The caller reads each one (trips.py)."""
    import time
    path = _envelope()
    if not path:
        return []
    vdir = os.path.dirname(os.path.dirname(path))
    db = sqlite3.connect('file:%s?mode=ro' % quote(path), uri=True, timeout=5)
    try:
        mc = _cols(db, 'messages')
        have = {r[0] for r in db.execute("select name from sqlite_master where type='table'")}
        if not {'subjects', 'addresses', 'mailboxes'} <= have or not {'sender', 'subject', 'mailbox'} <= mc:
            return []
        gd = _cols(db, 'message_global_data') if 'message_global_data' in have else set()
        g_join = g_col = ''
        if 'global_message_id' in mc and 'message_id_header' in gd:
            g_join, g_col = 'left join message_global_data g on g.ROWID = m.global_message_id', ', g.message_id_header mid'
        date = 'm.date_received' if 'date_received' in mc else 'm.date_sent'
        where = '%s > ?' % date + (' and m.deleted = 0' if 'deleted' in mc else '')
        rows = db.execute('select m.ROWID, s.subject, a.address, a.comment, %s, mb.url %s from messages m'
                          ' join subjects s on s.ROWID = m.subject left join addresses a on a.ROWID = m.sender'
                          ' join mailboxes mb on mb.ROWID = m.mailbox %s where %s order by %s desc limit 20000'
                          % (date, g_col, g_join, where, date), ((now or time.time()) - days * 86400,)).fetchall()
    finally:
        db.close()
    out, seen = [], set()
    for r in rows:
        rowid, subj, addr, name, dt, url = r[:6]
        if not match(subj or '', addr or ''):
            continue
        mid = ((r[6] if g_col else '') or '').strip().strip('<>').strip() or None
        acc_id, box, base = _mailbox(url, vdir)
        if (re.search(r'trash|deleted|junk|spam|papirkurv|uønsket|drafts|kladder|outbox', box or '', re.I)
                or SENT_RE.search(box or '') or not account_names.get(acc_id)):
            continue
        if mid and mid in seen:
            continue
        p = _emlx(base, rowid)
        if not p:
            continue
        seen.add(mid)
        out.append({'path': p, 'account': account_names.get(acc_id), 'message_id': mid, 'subject': subj or '',
                    'from_name': name or '', 'from_address': (addr or '').lower(), 'date': _iso_ts(dt), 'mailbox': box})
        if len(out) >= limit:
            break
    return out


SENT_RE = re.compile(r'(^|/)(sent|sent messages|sent items|sent mail|sendt|sendte elementer|sendte|gesendet|gesendete elemente|verzonden|envoyés)$', re.I)


def correspondence(account_names, own, days=60, limit=4000, now=None):
    """Who wrote to you and whom you wrote to, from Mail's index only (no message text): a list of
    {'dir': 'in'|'out', 'addr', 'name', 'date' (epoch), 'rowid', 'base', 'mid', 'subject', 'account', 'to', 'direct'} newest
    first ('direct': for 'in', whether one of your addresses was in To – None when Mail's index doesn't say).
    'in' = in a mailbox that isn't Sent/Trash/Junk and not from you; 'out' = in a Sent mailbox (with its To addresses)."""
    import time
    path = _envelope()
    if not path:
        return []
    vdir = os.path.dirname(os.path.dirname(path))
    own = {a.lower() for a in own if a}
    db = sqlite3.connect('file:%s?mode=ro' % quote(path), uri=True, timeout=5)
    try:
        mc = _cols(db, 'messages')
        have = {r[0] for r in db.execute("select name from sqlite_master where type='table'")}
        if not {'subjects', 'addresses', 'mailboxes'} <= have or not {'sender', 'subject', 'mailbox'} <= mc:
            return []
        gd = _cols(db, 'message_global_data') if 'message_global_data' in have else set()
        g_join = g_col = ''
        if 'global_message_id' in mc and 'message_id_header' in gd:
            g_join, g_col = 'left join message_global_data g on g.ROWID = m.global_message_id', ', g.message_id_header'
        date = 'm.date_received' if 'date_received' in mc else 'm.date_sent'
        where = '%s > ?' % date + (' and m.deleted = 0' if 'deleted' in mc else '')
        rows = db.execute('select m.ROWID, s.subject, a.address, a.comment, %s, mb.url %s from messages m'
                          ' join subjects s on s.ROWID = m.subject left join addresses a on a.ROWID = m.sender'
                          ' join mailboxes mb on mb.ROWID = m.mailbox %s where %s order by %s desc limit ?'
                          % (date, g_col, g_join, where, date), ((now or time.time()) - days * 86400, limit)).fetchall()
        rc = _cols(db, 'recipients') if 'recipients' in have else set()
        out = []
        for r in rows:
            rowid, subj, addr, name, dt, url = r[:6]
            acc_id, box, base = _mailbox(url, vdir)
            if not account_names.get(acc_id) or re.search(r'trash|deleted|junk|spam|papirkurv|uønsket|drafts|kladder|outbox', box or '', re.I):
                continue
            addr = (addr or '').lower()
            sent = bool(SENT_RE.search(box or '')) or addr in own
            to = []
            direct = None
            if sent and {'message', 'address'} <= rc:
                to = [(c or '', (a or '').lower()) for c, a in db.execute(
                    'select ra.comment, ra.address from recipients r join addresses ra on ra.ROWID = r.address where r.message = ? limit 20',
                    (rowid,)).fetchall() if a]
            elif not sent and {'message', 'address', 'type'} <= rc:
                # were you in To (type 0) – not only Cc / Bcc or a list? (reply debt counts direct asks only)
                direct = any((a or '').lower() in own for (a,) in db.execute(
                    'select ra.address from recipients r join addresses ra on ra.ROWID = r.address where r.message = ? and r.type = 0 limit 50',
                    (rowid,)).fetchall())
            out.append({'dir': 'out' if sent else 'in', 'addr': addr, 'name': name or '', 'date': float(dt or 0), 'rowid': rowid,
                        'base': base, 'mid': ((r[6] if g_col else '') or '').strip().strip('<>') or None, 'subject': subj or '',
                        'account': account_names.get(acc_id), 'to': to, 'direct': direct})
        return out
    finally:
        db.close()


def message_text(row):
    """The plain text of one message from correspondence() (the .emlx on disk), or ''."""
    p = _emlx(row.get('base'), row['rowid'])
    if not p:
        return '', False
    try:
        msg = email.message_from_bytes(_raw(p), policy=email.policy.default)
        return _text(msg), bool(_attachments(msg))
    except Exception:
        return '', False


# ---------- 2. Spotlight (words in the text) ----------
def _query(words):
    parts = []
    for w in words:
        parts.append('(kMDItemSubject == "*%s*"cd || kMDItemAuthors == "*%s*"cd || kMDItemAuthorEmailAddresses == "*%s*"cd'
                     ' || kMDItemRecipients == "*%s*"cd || kMDItemRecipientEmailAddresses == "*%s*"cd'
                     ' || kMDItemTextContent == "%s*"cd)' % ((w,) * 6))
    return 'kMDItemContentType == "com.apple.mail.emlx" && ' + ' && '.join(parts)


def _where(path, account_names):
    """(account name or None, mailbox) from …/Mail/V10/<account id>/<Box>.mbox/<Sub>.mbox/…/Messages/123.emlx"""
    parts = os.path.relpath(path, MAIL_DIR).split(os.sep)
    acc = parts[1] if len(parts) > 2 and re.match(r'^V\d+$', parts[0]) else None
    boxes = [p[:-5] for p in parts if p.endswith('.mbox')]
    return account_names.get(acc), '/'.join(boxes)


def search_spotlight(words, account_names, own, limit, timeout=15, before=None):
    try:
        r = subprocess.run(['/usr/bin/mdfind', '-onlyin', MAIL_DIR, _query(words)], capture_output=True, text=True, timeout=timeout)
    except (subprocess.TimeoutExpired, OSError):
        return []
    dated = []
    for p in [p for p in r.stdout.splitlines() if p.endswith('.emlx')][:2000]:
        try:
            t = os.path.getmtime(p)
        except OSError:
            continue
        if before is None or t < float(before):
            dated.append((t, p))
    dated.sort(reverse=True)
    out = []
    for _, p in dated[:limit]:
        rp = _inside(p)
        if not rp:
            continue
        try:
            h = BytesHeaderParser(policy=email.policy.compat32).parsebytes(_raw(rp, headers_only=True))
        except Exception:
            continue
        mid = (h.get('Message-ID') or '').strip().strip('<>').strip() or None
        name, addr = email.utils.parseaddr(_dec(h.get('From')))
        acc, box = _where(rp, account_names)
        addrs = [a for _, a in email.utils.getaddresses([_dec(h.get(k)) for k in ('From', 'To', 'Cc', 'Reply-To', 'Sender') if h.get(k)]) if a]
        out.append({'token': _token({'path': rp, 'account': acc, 'mid': mid}), 'subject': _dec(h.get('Subject')) or '(no subject)',
                    'from_name': name, 'from_address': addr, 'from_me': addr.lower() in own, 'to': _dec(h.get('To'))[:200],
                    'date': _iso(h.get('Date')), 'message_id': mid, 'account': acc, 'mailbox': box,
                    'has_attachments': True if 'multipart/mixed' in (h.get('Content-Type') or '').lower() else None, '_addrs': addrs})
    return out


def search(q, account_names, own_addresses=(), limit=40, classify=None, before=None):
    """Newest first, both sources merged. account_names: Mail's account id → the account name used in Axella – mail in
    other accounts is left out. classify(addresses) → (level, name): a message that involves a hidden contact is left
    out, one that involves a private contact comes back as who/when only, with no token to open it."""
    words = _words(q)
    if not words:
        return []
    own = {a.lower() for a in own_addresses if a}
    err, found = None, []
    try:
        found = search_index(words, account_names, own, limit, before)
    except SearchError as e:
        err = e
    except sqlite3.Error as e:
        err = SearchError("Mail's index couldn't be read: %s" % e)
    ids = {f['message_id'] for f in found if f['message_id']}
    for f in search_spotlight(words, account_names, own, limit, before=before):
        if f['message_id'] not in ids:
            found.append(f)
    if not found and err:
        raise err
    out = []
    for f in found:
        addrs = f.pop('_addrs', [])
        if not f.get('account'):                    # an account Axella isn't set up for
            _TOK.pop(f['token'], None)
            continue
        level, who = classify(addrs) if classify else (None, None)
        if level == 'hidden':
            _TOK.pop(f['token'], None)
            continue
        if level == 'private':
            _TOK.pop(f['token'], None)
            f = {'token': None, 'private': True, 'subject': '', 'from_name': who or 'Private contact', 'from_address': '',
                 'from_me': False, 'to': '', 'date': f['date'], 'message_id': None, 'account': f['account'],
                 'mailbox': '', 'has_attachments': None}
        out.append(f)
    out.sort(key=lambda f: f['date'] or '', reverse=True)
    return out[:limit]


def addresses_of(path):
    """Every address in a message file's From/To/Cc/Reply-To/Sender – for the private-contact check."""
    rp = _inside(path) if path else None
    if not rp:
        return []
    h = BytesHeaderParser(policy=email.policy.compat32).parsebytes(_raw(rp, headers_only=True))
    return [a for _, a in email.utils.getaddresses([_dec(h.get(k)) for k in ('From', 'To', 'Cc', 'Reply-To', 'Sender') if h.get(k)]) if a]


def sender_of(path):
    """(From address, Date as ISO) of a message file – what Macuse needs to find the mail in Mail (by_reference)."""
    rp = _inside(path) if path else None
    if not rp:
        return '', ''
    h = BytesHeaderParser(policy=email.policy.compat32).parsebytes(_raw(rp, headers_only=True))
    a = email.utils.getaddresses([_dec(h.get('From') or '')])
    try:
        when = email.utils.parsedate_to_datetime(h.get('Date')).isoformat() if h.get('Date') else ''
    except (TypeError, ValueError):
        when = ''
    return (a[0][1] if a and a[0][1] else ''), when


# ---------- reading a found message ----------
def _entry(token):
    import time
    e = _TOK.get(str(token or ''))
    if e and time.time() - e.get('_at', 0) > TOKEN_TTL:
        _TOK.pop(str(token), None)
        e = None
    if not e:
        raise SearchError('search again – this result has expired')
    if not e.get('path') and e.get('base') and e.get('rowid'):
        e['path'] = _emlx(e['base'], e['rowid'], deep=True)
    rp = _inside(e['path']) if e.get('path') else None
    if not rp:
        raise NotDownloaded(e.get('account'), e.get('mid'))
    return rp


def _text(msg):
    part = msg.get_body(preferencelist=('plain', 'html'))
    if part is None:
        return ''
    try:
        body = part.get_content()
    except Exception:
        body = (part.get_payload(decode=True) or b'').decode('utf-8', 'replace')
    if part.get_content_type() == 'text/html':
        body = re.sub(r'(?is)<(script|style|head)\b.*?</\1>', '', body)
        body = re.sub(r'(?i)<br\s*/?>|</(p|div|tr|li|h\d)>', '\n', body)
        body = html.unescape(re.sub(r'<[^>]+>', '', body))
        body = re.sub(r'\n[ \t]*\n[\s]*', '\n\n', body)
    return body.replace('\r\n', '\n').strip()


def _attachments(msg):
    """Every part with a file name, wherever it sits: Apple Mail puts a PDF you attach inline, inside
    multipart/alternative → multipart/mixed, where iter_attachments() doesn't look."""
    return [a for a in msg.walk() if not a.is_multipart() and a.get_filename()]


def _disk_attachment(emlx_path, name):
    """Mail keeps big attachments next to the mailbox (…/Attachments/<id>/<n>/<file>) and only their headers in the
    .partial.emlx – read the file from there."""
    base = os.path.basename(emlx_path).split('.')[0]
    root = os.path.join(os.path.dirname(os.path.dirname(emlx_path)), 'Attachments', base)
    for f in sorted(glob.glob(os.path.join(glob.escape(root), '*', '*'))):
        rf = os.path.realpath(f)
        if os.path.basename(f) == name and _inside_mail(rf) and os.path.isfile(rf) and os.path.getsize(rf) <= 50 * 2**20:
            with open(rf, 'rb') as fh:
                return fh.read()
    return None


def _inside_mail(rp):
    root = os.path.realpath(MAIL_DIR)
    return rp.startswith(root + os.sep)


def read(token, pics=False):
    """Preview of a found message – the same shape as the dashboard's message preview."""
    rp = _entry(token)
    hr = _safe_html(rp, pics)
    msg = BytesParser(policy=email.policy.default).parsebytes(_raw(rp))
    body = _text(msg)
    return {'subject': str(msg.get('Subject') or ''), 'from': str(msg.get('From') or ''),
            'date': (_iso(str(msg.get('Date') or '')) or '').replace('T', ' ')[:16],
            'mailbox': _where(rp, {})[1], 'attachments': [_dec(a.get_filename()) for a in _attachments(msg)],
            'body': body[:20000], 'truncated': len(body) > 20000, 'html': hr[0], 'remote_pics': hr[1]}


def _safe_html(rp, pics=False):
    try:
        return html_and_remote(rp, pics)
    except Exception:
        return None, False


HTML_MAX = 1500000


def path_for_mid(mid):
    """The .emlx file of a message, found by its Message-ID in Mail's index (None if Mail hasn't got it on disk)."""
    path = _envelope()
    if not path or not mid:
        return None
    vdir = os.path.dirname(os.path.dirname(path))
    db = sqlite3.connect('file:%s?mode=ro' % quote(path), uri=True, timeout=5)
    try:
        if 'message_id_header' not in _cols(db, 'message_global_data') or 'global_message_id' not in _cols(db, 'messages'):
            return None
        m = mid.strip().strip('<>')
        rows = db.execute('select m.ROWID, mb.url from messages m join message_global_data g on g.ROWID = m.global_message_id'
                          ' join mailboxes mb on mb.ROWID = m.mailbox where g.message_id_header in (?, ?) limit 5',
                          ('<%s>' % m, m)).fetchall()
    finally:
        db.close()
    for rowid, url in rows:
        p = _emlx(_mailbox(url, vdir)[2], rowid)
        if p:
            return p
    return None


_KEY = secrets.token_bytes(32)                     # signs picture links this process made (restart = new key)
PROXY = '/axella/api/img?u=%s&k=%s'
BLANK = 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7'


def _sign(u):
    import hashlib
    import hmac
    return hmac.new(_KEY, u.encode('utf-8', 'replace'), hashlib.sha256).hexdigest()[:32]


# ---------- the mail's HTML, made safe: an allow-list sanitiser (known tags and attributes only) ----------
from html.parser import HTMLParser  # noqa: E402

TAGS = {'a', 'abbr', 'address', 'article', 'aside', 'b', 'bdi', 'bdo', 'big', 'blockquote', 'body', 'br', 'caption',
        'center', 'cite', 'code', 'col', 'colgroup', 'dd', 'del', 'details', 'dfn', 'div', 'dl', 'dt', 'em', 'figcaption',
        'figure', 'font', 'footer', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'header', 'hr', 'i', 'img', 'ins', 'kbd', 'li',
        'main', 'mark', 'nav', 'ol', 'p', 'pre', 'q', 's', 'samp', 'section', 'small', 'span', 'strike', 'strong', 'sub',
        'summary', 'sup', 'table', 'tbody', 'td', 'tfoot', 'th', 'thead', 'time', 'tr', 'tt', 'u', 'ul', 'var', 'wbr'}
VOID = {'br', 'col', 'hr', 'img', 'wbr'}
SKIP = {'script', 'title', 'iframe', 'frame', 'frameset', 'object', 'embed', 'applet', 'noscript', 'svg', 'math',
        'template', 'select', 'textarea', 'button', 'audio', 'video', 'canvas', 'map', 'xml', 'noembed', 'noframes'}
ATTRS = {'align', 'alt', 'bgcolor', 'border', 'cellpadding', 'cellspacing', 'class', 'color', 'colspan', 'dir', 'face',
         'height', 'lang', 'rowspan', 'size', 'span', 'start', 'style', 'title', 'type', 'valign', 'width', 'nowrap',
         'href', 'src', 'background', 'id', 'name', 'datetime', 'cite'}
URL_ATTRS = {'href', 'src', 'background', 'cite'}
_CTRL = re.compile(r'[\x00-\x20\x7f]+')


def _clean_url(v):
    """The URL as a browser would read it: entities are already decoded by the parser; control characters and
    spaces inside a scheme ("java\tscript:") are dropped."""
    return _CTRL.sub('', v or '')


class _Sanitizer(HTMLParser):
    def __init__(self, cids, pics):
        super().__init__(convert_charrefs=True)
        self.cids, self.pics, self.out, self.skip, self.in_style, self.remote = cids, pics, [], [], False, False

    # pictures: inline (cid:/data:image) as they are, the internet only through the signed proxy, everything else blank
    def picture(self, v, css=False):
        u = _clean_url(v)
        low = u.lower()
        if low.startswith('cid:'):
            return self.cids.get(u[4:].strip('<>'), BLANK)
        if re.match(r'data:image/(png|jpe?g|gif|webp);', low):
            return u
        if low.startswith('//'):
            u, low = 'https:' + u, 'https:' + low
        if low.startswith(('http://', 'https://')):
            self.remote = True
            if self.pics:
                return PROXY % (quote(u, safe=''), _sign(u))
            return 'about:blank' if css else BLANK
        return 'about:blank' if css else BLANK

    def css(self, text):
        """CSS from a style attribute or <style>: no @import, no expressions/bindings, url() only for pictures."""
        t = re.sub(r'\\[0-9a-fA-F]{1,6}\s?|\\(.)', lambda m: m.group(1) or '', text)   # no CSS escapes ("u\\72l(")
        t = re.sub(r'/\*.*?\*/', '', t, flags=re.S)
        t = re.sub(r'(?i)@import[^;]*;?', '', t)
        t = re.sub(r'(?i)(expression|behavior|-moz-binding|javascript:|vbscript:)', 'x-blocked', t)
        t = re.sub(r'(?i)url\(\s*([\'"]?)(.*?)\1\s*\)', lambda m: 'url("%s")' % self.picture(m.group(2), css=True).replace('"', '%22'), t)
        t = re.sub(r'(?i)(-webkit-)?image-set\s*\(', 'x-blocked(', t)          # image-set("https://…") needs no url()
        t = re.sub(r'(?i)url\((?!"(about:blank|data:image/|/axella/api/img\?))', 'x-blocked(', t)   # anything url() left over
        t = re.sub(r'(?i)\bhttps?://', 'blocked:', t)                     # no bare web address left in CSS at all
        return t.replace('<', '').replace('>', '')

    def handle_starttag(self, tag, attrs, closing=False):
        tag = tag.lower()
        if self.skip:
            if tag in SKIP and tag not in VOID:
                self.skip.append(tag)
            return
        if tag in SKIP:
            self.skip.append(tag)
            return
        if tag == 'style':
            self.in_style = True
            self.out.append('<style>')
            return
        if tag not in TAGS:
            return                                  # html, head, meta, link, base, form, input …: tag dropped, text kept
        keep = []
        for k, v in attrs:
            k = (k or '').lower()
            if k not in ATTRS or v is None:
                continue
            if k == 'href':
                u = _clean_url(v)
                if not re.match(r'(?i)(https?:|mailto:|tel:|#)', u):
                    continue
                v = u
            elif k in ('src', 'background'):
                v = self.picture(v)
            elif k == 'cite':
                continue
            elif k == 'style':
                v = self.css(v)
            keep.append(' %s="%s"' % (k, html.escape(v, quote=True)))
        if tag == 'img' and any(k == ' src="%s"' % BLANK for k in [x for x in keep if x.startswith(' src=')]) and not self.pics:
            keep = [x for x in keep if not x.startswith((' width=', ' height=', ' style='))] + [' data-blocked=""']
        if tag == 'a':
            keep.append(' rel="noopener noreferrer"')
        self.out.append('<%s%s%s>' % (tag, ''.join(keep), ' /' if closing and tag in VOID else ''))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs, closing=True)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if self.skip:
            if tag == self.skip[-1]:
                self.skip.pop()
            return
        if tag == 'style' and self.in_style:
            self.in_style = False
            self.out.append('</style>')
        elif tag in TAGS and tag not in VOID:
            self.out.append('</%s>' % tag)

    def handle_data(self, data):
        if self.skip:
            return
        self.out.append(self.css(data) if self.in_style else html.escape(data, quote=False))

    def handle_comment(self, data):
        pass                                        # conditional comments and the like: gone

    def unknown_decl(self, data):
        pass


def sanitize(h, cids=None, pics=False):
    """(safe html, has remote pictures)."""
    s = _Sanitizer(cids or {}, pics)
    s.feed(h)
    s.close()
    out = ''.join(s.out)
    if s.in_style:
        out += '</style>'
    return out, s.remote


def has_remote(h):
    return bool(h) and sanitize(h)[1]


def html_of(path, pics=False):
    return html_and_remote(path, pics)[0]


def html_and_remote(path, pics=False):
    """The mail's own HTML, made safe to show in a sandboxed frame (no scripts allowed there anyway) by an allow-list
    sanitiser: known tags and attributes only, every URL checked after decoding, CSS without @import or expressions,
    images sent inside the mail (cid:) inlined, links open in a new tab. Pictures from the internet are blanked –
    unless pics=True: then their links point to the Mac mini's picture proxy (fetch_image), signed so only links made
    here are fetched."""
    if not path:
        return None, False
    msg = BytesParser(policy=email.policy.default).parsebytes(_raw(path))
    part = msg.get_body(preferencelist=('html',))
    if part is None:
        return None, False
    try:
        h = part.get_content()
    except Exception:
        h = (part.get_payload(decode=True) or b'').decode('utf-8', 'replace')
    if len(h) > HTML_MAX:
        return None, False
    import base64
    cids = {}
    for p in msg.walk():
        cid = (p.get('Content-ID') or '').strip().strip('<>')
        if cid and p.get_content_maintype() == 'image' and p.get_content_type() != 'image/svg+xml':
            data = p.get_payload(decode=True) or b''
            if 0 < len(data) < 1500000:
                cids[cid] = 'data:%s;base64,%s' % (p.get_content_type(), base64.b64encode(data).decode())
    h, remote = sanitize(h, cids, pics)
    return ('<base target="_blank"><meta name="referrer" content="no-referrer">'
            '<style>body{margin:12px;font:14px/1.45 -apple-system,BlinkMacSystemFont,"Helvetica Neue",Arial,sans-serif;'
            'color:#1d1d1f;background:#fff;overflow-wrap:anywhere}img{max-width:100%;height:auto}'
            'img[data-blocked]{display:none}</style>' + h), remote   # a blocked picture leaves no empty box


IMG_MAX = 5 * 2**20
IMG_TYPES = ('image/png', 'image/jpeg', 'image/gif', 'image/webp', 'image/bmp', 'image/x-icon', 'image/vnd.microsoft.icon')
CACHE_BYTES = 50 * 2**20                            # all cached pictures together
import collections  # noqa: E402
_IMG_CACHE = collections.OrderedDict()


def _cache_put(u, v):
    _IMG_CACHE[u] = v
    _IMG_CACHE.move_to_end(u)
    while sum(len(x[1]) for x in _IMG_CACHE.values()) > CACHE_BYTES and len(_IMG_CACHE) > 1:
        _IMG_CACHE.popitem(last=False)


def _global(ip):
    import ipaddress
    try:
        return ipaddress.ip_address(str(ip).split('%')[0]).is_global
    except ValueError:
        return False


def _public_ip(host, port, resolve=None):
    """The addresses to connect to – only if EVERY address the name resolves to is on the public internet. The
    connection then goes to exactly these (no second lookup a sender's DNS could answer differently)."""
    import socket
    try:
        infos = (resolve or socket.getaddrinfo)(host, port, 0, socket.SOCK_STREAM)
    except OSError:
        return None
    ips = list(dict.fromkeys(i[4][0] for i in infos))
    return ips if ips and all(_global(ip) for ip in ips) else None


def _public(host):
    return _public_ip(host, 443) is not None


IMG_ACCEPT = 'image/png,image/jpeg,image/gif,image/webp,image/*;q=0.8'
IMG_AGENT = 'Mozilla/5.0 (Macintosh) AppleWebKit (Axella picture proxy)'


def pinned_get(url, resolve=None, connect=None, accept=IMG_ACCEPT, limit=None, timeout=8, agent=IMG_AGENT, what='picture'):
    """One GET to a pinned, checked address: the name is resolved once, every address must be public, the socket goes
    to exactly one of those and its peer is checked again (getpeername) before anything is sent. No redirects are
    followed here – the caller checks each hop. Returns (status, headers, body ≤ limit+1 bytes; only for 200)."""
    import http.client
    import socket
    import ssl
    limit = IMG_MAX if limit is None else limit
    p = urlparse(url)
    if p.scheme not in ('http', 'https') or not p.hostname:
        raise SearchError('%s not allowed' % what)
    port = p.port or (443 if p.scheme == 'https' else 80)
    ips = _public_ip(p.hostname, port, resolve)
    if not ips:
        raise SearchError('%s not allowed' % what)
    try:
        sock = None
        for ip in ips[:4]:                          # e.g. IPv6 first, IPv4 when that has no route – all checked above
            try:
                sock = (connect or socket.create_connection)((ip, port), timeout)
                break
            except OSError:
                continue
        if sock is None:
            raise OSError('no address answered')
        if not _global(sock.getpeername()[0]):
            sock.close()
            raise SearchError('%s not allowed' % what)
        if p.scheme == 'https':
            sock = ssl.create_default_context().wrap_socket(sock, server_hostname=p.hostname)
        conn = http.client.HTTPConnection(p.hostname, port, timeout=timeout)    # Host header from the name …
        conn.sock = sock                                                         # … the connection to the checked address
        path = (p.path or '/') + ('?' + p.query if p.query else '')
        conn.request('GET', path, headers={'User-Agent': agent, 'Accept': accept, 'Accept-Encoding': 'identity'})
        r = conn.getresponse()
        body = r.read(limit + 1) if r.status == 200 else b''
        conn.close()
        return r.status, r.headers, body
    except SearchError:
        raise
    except (OSError, http.client.HTTPException, ssl.SSLError):
        raise SearchError('%s not reachable' % what)


def _get(url, resolve=None, connect=None):
    """One GET for the picture proxy (pinned, checked address). Returns (status, headers, body ≤ IMG_MAX+1 bytes)."""
    return pinned_get(url, resolve, connect)


def fetch_image(u, k, resolve=None, connect=None):
    """(content type, bytes) of a picture from the internet, for a link html_of signed. No cookies, no referrer,
    public addresses only – checked once and then connected to directly, also after redirects – pictures only (no
    SVG), at most 5 MB each, 50 MB cached in all."""
    import hmac
    from urllib.parse import urljoin
    if not u or not k or not hmac.compare_digest(_sign(u), str(k)):
        raise SearchError('not a picture link from a mail')
    if u in _IMG_CACHE:
        _IMG_CACHE.move_to_end(u)
        return _IMG_CACHE[u]
    url = u
    for _ in range(4):
        status, headers, data = _get(url, resolve, connect)
        if status in (301, 302, 303, 307, 308) and headers.get('Location'):
            url = urljoin(url, headers['Location'])
            continue
        if status != 200:
            raise SearchError('picture not found (%d)' % status)
        ctype = (headers.get('Content-Type') or '').split(';')[0].strip().lower()
        if ctype not in IMG_TYPES:
            raise SearchError('not a picture')
        if len(data) > IMG_MAX:
            raise SearchError('picture too large')
        _cache_put(u, (ctype, data))
        return ctype, data
    raise SearchError('too many redirects')


def attachment(token, n):
    """(file name, content type, bytes) of attachment n (1-based) of a found message."""
    rp = _entry(token)
    msg = BytesParser(policy=email.policy.default).parsebytes(_raw(rp))
    atts = _attachments(msg)
    i = int(n) - 1
    if not 0 <= i < len(atts):
        raise SearchError('no such attachment')
    data = atts[i].get_payload(decode=True) or b''
    if not data:                                   # kept outside the .emlx by Mail
        data = _disk_attachment(rp, _dec(atts[i].get_filename())) or b''
    if not data:                                   # only the headers are on disk: let Mail fetch it
        e = _TOK.get(str(token or '')) or {}
        if e.get('account') and e.get('mid'):
            raise NotDownloaded(e['account'], e['mid'])
        raise SearchError("Mail hasn't downloaded this attachment yet")
    name = re.sub(r'[\x00-\x1f/\\]', '_', _dec(atts[i].get_filename()))[:200] or 'attachment'
    return name, atts[i].get_content_type(), data


ACCOUNTS_SCRIPT = '''
tell application "Mail"
  set out to ""
  repeat with a in every account
    set out to out & (id of a) & tab & (name of a) & linefeed
  end repeat
  return out
end tell
'''
