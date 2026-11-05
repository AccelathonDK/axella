#!/usr/bin/env python3
"""Private-contact filter between Claude runs and Macuse (MCP over stdio).

Started by the scheduler instead of Macuse whenever Mail or iMessage has private or hidden contacts
(state/mcp-filtered.json → `python3 setup/mcp_filter.py state/mcp.json`). It starts the real Macuse server from
state/mcp.json and passes every message through unchanged – except the results of Mail and Messages tools: anything
that involves a private or hidden contact (their e-mail address or phone number anywhere in it) is removed before
Claude sees it. It errs on the safe side: a mail where the contact is only in Cc is removed whole, a string that
mentions them is dropped, and plain text that mentions them anywhere is withheld entirely.

  mail_*      – checked against the contacts whose Mail level isn't "normal"
  messages_*  – iMessage/SMS, against the contacts whose iMessage level isn't "normal"
  calendar_*  – invites and notes: against anyone private or hidden on Mail or iMessage
  If the Mail or iMessage default is private or hidden, every result of its tools is withheld (not the calendar).

Nothing is said about what was removed (Claude can't tell that anything was), and nothing is logged with content.
"""
import json
import os
import re
import subprocess
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(os.path.dirname(HERE), 'state')
sys.path.insert(0, HERE)
import privacy  # noqa: E402

CHANNEL = {'mail_': 'mail', 'messages_': 'imessage', 'calendar_': 'calendar'}
GONE = 'Not available.'


def channel_of(tool):
    for p, ch in CHANNEL.items():
        if tool.startswith(p):
            return ch
    return None


class Matcher:
    """Finds a private contact's address or number in any text."""
    def __init__(self, pv, channel):
        d = pv.load()
        cal = channel == 'calendar'                     # invites/notes: anyone private on Mail or iMessage
        chans = ('mail', 'imessage') if cal else (channel,)
        # privacy.json unreadable: every result counts as private (Privacy.strict) – calendar included
        self.all = bool(d.get('broken')) or (not cal and d['defaults'].get(channel, 'normal') != 'normal')
        mails, phones, names = set(), set(), set()
        for c in d['contacts']:
            lvls = [(c.get('levels') or {}).get(ch) or (c.get('levels') or {}).get('all') or d['defaults'].get(ch, 'normal') for ch in chans]
            if all(lvl == 'normal' for lvl in lvls):
                continue
            if channel in ('imessage', 'calendar') and len((c.get('name') or '').strip()) >= 3:
                names.add(c['name'].strip().lower())    # Messages shows names from Contacts instead of numbers
            for i in c.get('ids') or []:
                n = privacy.norm(i)
                if '@' in n:
                    mails.add(n)
                elif n.isdigit():
                    phones.add(n[-8:])
        self.mails = mails
        self.phones = phones                            # last 8 digits; matched against every number-like run of text
        self.names = [re.compile(r'(?<!\w)' + re.escape(n) + r'(?!\w)', re.I) for n in names]

    def empty(self):
        return not self.all and not self.mails and not self.phones and not self.names

    NUM = re.compile(r'\+?\d[\d\s.\-()]{5,}\d')

    def hit(self, text):
        t = text.lower()
        if any(m in t for m in self.mails) or any(n.search(text) for n in self.names):
            return True
        if self.phones:                                 # +45 00 11 22 33, +4500112233, 0011-2233 … all end the same way
            for run in self.NUM.findall(text):
                d = re.sub(r'\D', '', run)
                if any(d.endswith(p) for p in self.phones):
                    return True
        return False


WRAPPER_TEXT_KEYS = {'status', 'type', 'cursor', 'next_cursor', 'nextcursor', 'next_page_token', 'nextpagetoken', 'kind'}
# the list names a result container uses – a message made of lists ({"headers": [...], "parts": [...]}) is not one
WRAPPER_LIST_KEYS = {'messages', 'results', 'items', 'mails', 'emails', 'chats', 'conversations', 'threads', 'events',
                     'data', 'entries', 'records', 'matches', 'hits', 'list'}


def _is_wrapper(x):
    """A container like {"messages": [...], "count": 3, "next_cursor": "…"}: lists under known container names plus
    counters/bookkeeping only. A message ({"from", "subject", "body", "cc": [...]} or {"headers": [...], "parts": [...]})
    is never one."""
    if not any(isinstance(v, list) for v in x.values()):
        return False
    for k, v in x.items():
        if isinstance(v, list):
            if k.lower() not in WRAPPER_LIST_KEYS:
                return False
            continue
        if v is None or isinstance(v, (bool, int, float)):
            continue
        if isinstance(v, str) and k.lower() in WRAPPER_TEXT_KEYS and len(v) <= 200:
            continue
        return False
    return True


def _filter_json(x, m):
    """Anything that mentions a private contact is gone: a list element (object, list or string) is dropped, an object
    that mentions them becomes None – unless it is a pure wrapper, whose lists are filtered instead."""
    if isinstance(x, list):
        out = []
        for v in x:
            if m.hit(v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)):
                continue
            out.append(_filter_json(v, m))
        return out
    if isinstance(x, dict):
        if m.hit(json.dumps(x, ensure_ascii=False)):
            if not _is_wrapper(x):
                return None
            kept = {k: _filter_json(v, m) if isinstance(v, list) else v for k, v in x.items()}
            for k in ('count', 'total', 'total_count', 'totalCount'):     # don't give away that something was removed
                olds = [len(v) for v in x.values() if isinstance(v, list)]
                if isinstance(kept.get(k), int) and kept[k] in olds:
                    kept[k] = sum(len(v) for v in kept.values() if isinstance(v, list))
            return kept
        return {k: _filter_json(v, m) for k, v in x.items()}
    if isinstance(x, str) and m.hit(x):
        return GONE
    return x


def filter_text(text, m):
    """Plain text that mentions a private contact is withheld as a whole – a paragraph split can't tell where one
    message ends and the next begins. JSON text is filtered element by element."""
    if not m.hit(text):
        return text
    try:
        data = json.loads(text)
    except ValueError:
        return GONE
    out = _filter_json(data, m)
    return GONE if out is None else json.dumps(out, ensure_ascii=False)


def filter_result(tool, result, pv):
    ch = channel_of(tool)
    if not ch or not isinstance(result, dict):
        return result
    m = Matcher(pv, ch)
    if ch == 'calendar':
        m.all = False                                   # a whole platform set to private doesn't hide the calendar
    if m.empty():
        return result
    if m.all:
        return {'content': [{'type': 'text', 'text': GONE}], 'isError': False}
    content = []
    for c in result.get('content') or []:
        if isinstance(c, dict) and c.get('type') == 'text':
            content.append({**c, 'text': filter_text(c.get('text') or '', m)})
        elif isinstance(c, dict) and c.get('type') in ('image', 'resource', 'audio'):
            continue                                    # attachments/images can't be checked: never passed on
        else:
            content.append(c)
    out = {**result, 'content': content}
    if 'structuredContent' in result:
        sc = _filter_json(result['structuredContent'], m)
        out['structuredContent'] = sc if isinstance(sc, dict) else {}
    return out


def main(cfg_path):
    with open(cfg_path, encoding='utf-8') as f:
        srv = json.load(f)['mcpServers']['macuse']
    env = {**os.environ, **(srv.get('env') or {})}
    child = subprocess.Popen([srv['command']] + list(srv.get('args') or []), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             env=env, bufsize=0)
    pv = privacy.Privacy(STATE)
    pending, lock = {}, threading.Lock()

    def upstream():                                     # Claude → Macuse
        for line in sys.stdin.buffer:
            try:
                msg = json.loads(line)
                if isinstance(msg, dict) and msg.get('method') == 'tools/call' and 'id' in msg:
                    with lock:
                        pending[msg['id']] = str((msg.get('params') or {}).get('name') or '')
            except ValueError:
                pass
            try:
                child.stdin.write(line)
                child.stdin.flush()
            except (BrokenPipeError, OSError):
                break
        try:
            child.stdin.close()
        except OSError:
            pass

    threading.Thread(target=upstream, daemon=True).start()
    out = sys.stdout.buffer
    for line in child.stdout:                           # Macuse → Claude
        try:
            msg = json.loads(line)
        except ValueError:
            out.write(line)
            out.flush()
            continue
        if isinstance(msg, dict) and 'id' in msg and 'result' in msg:
            with lock:
                tool = pending.pop(msg['id'], None)
            if tool:
                try:
                    msg['result'] = filter_result(tool, msg['result'], pv)
                except Exception:                       # never pass an unchecked result on
                    msg['result'] = {'content': [{'type': 'text', 'text': GONE}], 'isError': True}
                line = (json.dumps(msg, ensure_ascii=False) + '\n').encode()
        out.write(line)
        out.flush()
    sys.exit(child.wait())


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(STATE, 'mcp.json'))
