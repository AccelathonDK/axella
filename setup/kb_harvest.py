"""Knowledge harvest – Axella learns facts from mail and proposes them as SUGGESTED knowledge entries.

Two kinds of run (the Claude task setup/local-tasks/kb-harvest.md, read-only for Mail):
  - nightly (01:30): the owner's sent mail since the last good run – facts from his own answers, corrections he made to
    Axella's drafts before sending, and active entries his newer mail contradicts ("may be outdated");
  - scans: the owner picks a part of the mailbox (a folder, sender/domain, date range – optionally tied to a project);
    the Mac mini works through it in batches at night (01:00–06:00, at most MAX_BATCHES a night), only threads he
    answered, and keeps the progress so a restart just continues.

Nothing here writes mail. Suggestions are never used until the owner approves them on the Knowledge page.
Work-mailbox (employer) suggestions are capped at visibility "internal".

Files: state/kb-harvest.json (nightly "since", scans + progress), state/kb/<rid>.request.json → state/kb/<rid>.json
(the run's result), merged results move to state/kb/done/ and are pruned after 14 days.
"""
import datetime
import glob
import json
import os
import re
import threading

import axprofile
from knowledge import Bad as KBad

LOCK = threading.Lock()
NIGHTLY_AT = '01:30'
WINDOW = ('01:00', '06:00')       # scan batches only run at night
MAX_BATCHES = 8                   # scan batches per night (8 × 15 threads)
BATCH = 15                        # threads per scan batch – small enough that one run gets through it
NIGHTLY_MAX = 80                  # sent mails per nightly run
KEEP_DAYS = 14
LEARNED = ('sent', 'draft-edit', 'thread')


class Bad(Exception):
    pass


def _now():
    return datetime.datetime.now().astimezone()


def _iso(dt=None):
    return (dt or _now()).isoformat(timespec='seconds')


def _hm(s):
    h, m = s.split(':')
    return int(h) * 60 + int(m)


def _norm_title(t):
    return re.sub(r'[\W_]+', ' ', str(t or '').lower()).strip()


class Harvest:
    def __init__(self, base, state_dir, kb, log=None):
        self.base, self.state_dir, self.kb, self.log = base, state_dir, kb, log
        self.file = os.path.join(state_dir, 'kb-harvest.json')
        self.dir = os.path.join(state_dir, 'kb')
        os.makedirs(os.path.join(self.dir, 'done'), exist_ok=True)

    # ---------- state ----------
    def load(self):
        try:
            with open(self.file, encoding='utf-8') as f:
                d = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            d = {}
        d.setdefault('nightly', {'enabled': True, 'since': None, 'last': None, 'last_result': None})
        d.setdefault('scans', [])
        d.setdefault('nights', {})          # date → scan batches started that night
        return d

    def _save(self, d):
        tmp = self.file + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.file)

    def status(self):
        with LOCK:
            d = self.load()
        n = sum(1 for e in self.kb.load() if e.get('status') == 'suggested')
        out = sum(1 for e in self.kb.load() if e.get('status') == 'active' and e.get('outdated'))
        return {'nightly': d['nightly'], 'scans': d['scans'][-30:], 'suggested': n, 'outdated': out,
                'batch': BATCH, 'max_batches': MAX_BATCHES, 'window': list(WINDOW), 'nightly_at': NIGHTLY_AT}

    # ---------- requests for the scheduler ----------
    def _write_request(self, rid, req):
        with open(os.path.join(self.dir, rid + '.request.json'), 'w', encoding='utf-8') as f:
            json.dump(req, f, ensure_ascii=False, indent=1)

    def nightly_request(self, rid):
        """Prepare tonight's sent-mail run. Returns False when switched off."""
        with LOCK:
            d = self.load()
            if not d['nightly'].get('enabled', True):
                return False
            since = d['nightly'].get('since') or _iso(_now() - datetime.timedelta(days=1))
            req = {'id': rid, 'mode': 'nightly', 'since': since, 'until': _iso(), 'max_mails': NIGHTLY_MAX}
            self._write_request(rid, req)
            d['nightly']['pending'] = {'rid': rid, 'until': req['until'], 'at': _iso()}
            self._save(d)
        return True

    def next_scan(self):
        """The scan to continue next (oldest first), or None."""
        with LOCK:
            d = self.load()
        for s in d['scans']:
            if s.get('status') in ('queued', 'running') and not s.get('pending'):
                return s
        return None

    def scan_request(self, rid, sid, night=None):
        with LOCK:
            d = self.load()
            s = next((x for x in d['scans'] if x['id'] == sid), None)
            if not s or s.get('status') not in ('queued', 'running'):
                return False
            req = {'id': rid, 'mode': 'scan', 'scan': {k: s.get(k) for k in ('id', 'label', 'mailbox', 'account', 'sender',
                   'query', 'start', 'end', 'project')}, 'offset': s.get('offset', 0), 'batch': BATCH}
            self._write_request(rid, req)
            s.update(status='running', pending={'rid': rid, 'at': _iso()})
            if night:
                d['nights'][night] = d['nights'].get(night, 0) + 1
                d['nights'] = dict(sorted(d['nights'].items())[-10:])
            self._save(d)
        return True

    def batches_tonight(self, night):
        with LOCK:
            return self.load()['nights'].get(night, 0)

    def clear_stale(self, active_refs):
        """A batch whose run ended without a result (failed twice) – count the failure, stop after 3."""
        with LOCK:
            d = self.load()
            changed = False
            for s in d['scans']:
                p = s.get('pending')
                if p and p['rid'] not in active_refs and not os.path.exists(os.path.join(self.dir, p['rid'] + '.json')):
                    age = (_now() - datetime.datetime.fromisoformat(p['at'])).total_seconds()
                    if age > 3600:
                        s['pending'] = None
                        s['fails'] = s.get('fails', 0) + 1
                        if s['fails'] >= 3:
                            s.update(status='paused', note='Stopped after 3 failed batches – see Runs')
                        changed = True
            p = d['nightly'].get('pending')
            if p and p['rid'] not in active_refs and not os.path.exists(os.path.join(self.dir, p['rid'] + '.json')):
                if (_now() - datetime.datetime.fromisoformat(p['at'])).total_seconds() > 3600:
                    d['nightly']['pending'] = None          # "since" stays – the next night covers it
                    d['nightly']['last_result'] = 'failed'
                    changed = True
            if changed:
                self._save(d)

    # ---------- results → suggested entries ----------
    def ingest(self):
        n = 0
        for p in sorted(glob.glob(os.path.join(self.dir, '*.json'))):
            if p.endswith('.request.json'):
                continue
            rid = os.path.basename(p)[:-5]
            try:
                with open(p, encoding='utf-8') as f:
                    res = json.load(f)
                with open(os.path.join(self.dir, rid + '.request.json'), encoding='utf-8') as f:
                    req = json.load(f)
            except (OSError, ValueError):
                if os.path.getmtime(p) < _now().timestamp() - 600:     # unreadable for 10 min – set it aside
                    os.replace(p, os.path.join(self.dir, 'done', rid + '.bad.json'))
                continue
            added, flagged = self._merge(res, req)
            n += added
            with LOCK:
                d = self.load()
                if req.get('mode') == 'nightly':
                    d['nightly'].update(since=req['until'], last=_iso(), pending=None,
                                        last_result='%d suggestion%s, %d flagged' % (added, '' if added == 1 else 's', flagged))
                else:
                    s = next((x for x in d['scans'] if x['id'] == req['scan']['id']), None)
                    if s:
                        # The offset is counted here, not taken from the model: offset + the threads it went through.
                        # The run only says whether the scope has more threads ("more", or next_offset null = no more).
                        try:
                            processed = max(0, int(res.get('processed') or 0))
                        except (TypeError, ValueError):
                            processed = 0
                        more = res.get('more')
                        if more is None:
                            more = res.get('next_offset') is not None
                        s['threads_done'] = s.get('threads_done', 0) + processed
                        s['suggestions'] = s.get('suggestions', 0) + added
                        s['pending'], s['last'] = None, _iso()
                        if res.get('total') is not None:
                            s['total'] = res['total']
                        if s.get('status') == 'running':
                            if processed:
                                s['offset'] = s.get('offset', 0) + processed
                                s['fails'] = 0
                            if not more:
                                s.update(status='done', ended=_iso())
                            elif not processed:          # read nothing but says there's more: try again, give up after 3
                                s['fails'] = s.get('fails', 0) + 1
                                if s['fails'] >= 3:
                                    s.update(status='paused', note='Stopped: 3 batches in a row read no threads – see Runs')
                        if res.get('note'):
                            s['note'] = str(res['note'])[:300]
                self._save(d)
            for x in (p, os.path.join(self.dir, rid + '.request.json')):
                try:
                    os.replace(x, os.path.join(self.dir, 'done', os.path.basename(x)))
                except OSError:
                    pass
        self._prune()
        return n

    def _merge(self, res, req):
        work = {a['id'] for a in axprofile.accounts() if a.get('kind') == 'work'}
        try:
            with open(os.path.join(self.state_dir, 'projects.json'), encoding='utf-8') as f:
                pj = json.load(f)
            pl = pj.get('projects', pj) if isinstance(pj, dict) else pj
            projects = {x.get('id') for x in (pl.values() if isinstance(pl, dict) else pl) if isinstance(x, dict)}
        except (OSError, ValueError, AttributeError):
            projects = set()
        entries = self.kb.load()
        by_title = {}
        for e in entries:
            by_title.setdefault(_norm_title(e.get('title')), e)
        added = flagged = 0
        for s in (res.get('suggestions') or [])[:60]:
            if not isinstance(s, dict) or not s.get('title') or not s.get('body'):
                continue
            src = [x for x in (s.get('sources') or []) if isinstance(x, dict)][:5]
            account = next((x.get('account') for x in src if x.get('account')), None)
            p = {'title': str(s['title'])[:200], 'body': str(s['body'])[:4000], 'status': 'suggested',
                 'category': s.get('category') if s.get('category') in ('employer', 'own company', 'holiday rental', 'private', 'other') else 'other',
                 'visibility': s.get('visibility') if s.get('visibility') in ('private', 'internal', 'shareable') else 'internal',
                 'language': s.get('language'), 'scope': s.get('scope') or 'overall',
                 'learned': s.get('learned') if s.get('learned') in LEARNED else 'sent',
                 'from_others': str(s.get('from_others'))[:120] if s.get('from_others') else None}
            if isinstance(p['scope'], list):                      # only real projects
                p['scope'] = [x for x in p['scope'] if x in projects] or 'overall'
            if req.get('mode') == 'scan' and req['scan'].get('project') and p['scope'] == 'overall':
                p['scope'] = [req['scan']['project']]
            if account in work:                                  # employer facts: never "shareable" by default
                p['category'] = 'employer'
                if p['visibility'] == 'shareable':
                    p['visibility'] = 'internal'
            sources = [{'kind': 'mail', 'ref': str(x.get('message_id') or '')[:500],
                        'label': str(x.get('label') or '')[:200], 'date': x.get('date')} for x in src]
            same = by_title.get(_norm_title(p['title']))
            if s.get('same_as'):
                same = next((e for e in entries if e['id'] == s['same_as']), same)
            try:
                if same:
                    if same.get('status') == 'suggested':          # add the new mail as one more source
                        for x in sources:
                            self.kb.action('kb_update', {'id': same['id'], 'source': x})
                    continue                                       # active: the outdated check covers changes; dismissed: respect it
                try:
                    eid = self.kb.action('kb_add', {**p, 'source': sources[0] if sources else {'kind': 'mail', 'label': 'From your mail'}})
                except KBad:
                    p['scope'] = 'overall'                         # e.g. a project id the run made up
                    eid = self.kb.action('kb_add', {**p, 'source': sources[0] if sources else {'kind': 'mail', 'label': 'From your mail'}})
                for x in sources[1:]:
                    self.kb.action('kb_update', {'id': eid, 'source': x})
                by_title[_norm_title(p['title'])] = {'id': eid, 'status': 'suggested'}
                added += 1
            except KBad as e:
                if self.log:
                    self.log.write('%s kb harvest: skipped a suggestion – %s\n' % (_iso(), e))
        active = {e['id'] for e in entries if e.get('status') == 'active'}
        for o in (res.get('outdated') or [])[:30]:
            if isinstance(o, dict) and o.get('id') in active:
                try:
                    self.kb.action('kb_update', {'id': o['id'], 'outdated': {
                        'reason': str(o.get('reason') or 'Newer mail says something else')[:300],
                        'source': {'kind': 'mail', 'ref': str(o.get('message_id') or '')[:500], 'label': str(o.get('label') or '')[:200]},
                        'at': _iso()}})
                    flagged += 1
                except KBad:
                    pass
        return added, flagged

    def _prune(self):
        cutoff = _now().timestamp() - KEEP_DAYS * 86400
        for p in glob.glob(os.path.join(self.dir, 'done', '*.json')):
            try:
                if os.path.getmtime(p) < cutoff:
                    os.remove(p)
            except OSError:
                pass

    # ---------- dashboard actions ----------
    def action(self, action, p):
        with LOCK:
            d = self.load()
            if action == 'kb_scan_add':
                mailbox = str(p.get('mailbox') or '').strip()[:200]
                sender = str(p.get('sender') or '').strip()[:200]
                query = str(p.get('query') or '').strip()[:200]
                if not (mailbox or sender or query):
                    raise Bad('choose a folder, a sender/domain or words to look for')
                for k in ('start', 'end'):
                    if p.get(k) and not re.match(r'^\d{4}-\d{2}-\d{2}$', str(p[k])):
                        raise Bad('bad date')
                proj = p.get('project') or None
                if proj and not re.match(r'^p-[\w-]{1,80}$', str(proj)):
                    raise Bad('bad project')
                if sum(1 for s in d['scans'] if s.get('status') in ('queued', 'running', 'paused')) >= 5:
                    raise Bad('at most 5 scans at a time – finish or cancel one first')
                sid = 's' + _now().strftime('%Y%m%d%H%M%S')
                label = str(p.get('label') or '').strip()[:80] or ' · '.join(x for x in (mailbox, sender, query) if x)
                d['scans'].append({'id': sid, 'label': label, 'mailbox': mailbox or None, 'account': p.get('account') or None,
                                   'sender': sender or None, 'query': query or None, 'start': p.get('start') or None,
                                   'end': p.get('end') or None, 'project': proj, 'status': 'queued', 'created': _iso(),
                                   'offset': 0, 'threads_done': 0, 'suggestions': 0, 'total': None, 'pending': None})
                d['scans'] = d['scans'][-50:]
                self._save(d)
                return sid
            if action == 'kb_nightly':
                d['nightly']['enabled'] = bool(p.get('enabled', True))
                self._save(d)
                return 'saved'
            s = next((x for x in d['scans'] if x['id'] == p.get('id')), None)
            if not s:
                raise Bad('scan not found')
            if action == 'kb_scan_pause' and s['status'] in ('queued', 'running'):
                s['status'] = 'paused'
            elif action == 'kb_scan_resume' and s['status'] == 'paused':
                s.update(status='queued', fails=0, note=None)
            elif action == 'kb_scan_cancel' and s['status'] not in ('done', 'cancelled'):
                s.update(status='cancelled', ended=_iso())
            elif action == 'kb_scan_remove' and s['status'] in ('done', 'cancelled'):
                d['scans'].remove(s)
            elif action == 'kb_scan_now':
                if s['status'] == 'paused':
                    s.update(status='queued', fails=0)
                if s['status'] not in ('queued', 'running'):
                    raise Bad('this scan is finished')
                s['now'] = True                                    # the scheduler starts one batch at once
            else:
                raise Bad('not possible now')
            self._save(d)
            return s['id']

    def take_now(self):
        """A scan the owner asked to run a batch of right now."""
        with LOCK:
            d = self.load()
            for s in d['scans']:
                if s.pop('now', None) and s.get('status') in ('queued', 'running') and not s.get('pending'):
                    self._save(d)
                    return s['id']
            self._save(d)
        return None
