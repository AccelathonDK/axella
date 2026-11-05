"""Forward receipts/invoices to bookkeepers and platforms – a closed circle.

state/recipients.json (written only by the dashboard, Settings → Bookkeeping recipients):
  {"recipients": [{"id", "name", "email", "project": id|null}]}
Only addresses in this list can ever receive a forward – an address found in a mail can never become a recipient.

Forwarding happens only from the dashboard (the owner's tap) or, later, by auto-forward rules the owner switches on per
vendor in the Receipts view. The scheduled Claude runs never forward anything.
Each forward is logged on the document ("sent": [{"to", "name", "at", "how"}]) and in state/actions.log, and teaches
the vendor rule: vendor_rules[vendor]["forward"] = {recipient_id: count}.
"""
import datetime
import json
import os
import re
import secrets
import threading

LOCK = threading.Lock()
EMAIL = re.compile(r'^[^@\s<>"]+@[^@\s<>"]+\.[^@\s<>"]+$')
DAILY_CAP = 40          # forwards per day, manual + auto
AUTO_AFTER = 3          # same choice this many times before auto-forward can be switched on


class Bad(Exception):
    pass


def _now():
    return datetime.datetime.now().astimezone().isoformat(timespec='seconds')


class Forwarding:
    def __init__(self, state_dir, docs, forward_fn):
        """docs: documents.Documents; forward_fn(account, message_id, address, name) does the actual Mail forward."""
        self.file = os.path.join(state_dir, 'recipients.json')
        self.docs = docs
        self.forward_fn = forward_fn

    def load(self):
        try:
            with open(self.file, encoding='utf-8') as f:
                d = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            d = {}
        d.setdefault('recipients', [])
        return d

    def _save(self, d):
        tmp = self.file + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.file)

    def _sent_today(self, reg):
        today = datetime.date.today().isoformat()
        return sum(1 for doc in reg['documents'].values() for s in doc.get('sent', []) if s.get('at', '').startswith(today))

    def forward(self, message_id, recipient_id, how='manual'):
        rec = next((r for r in self.load()['recipients'] if r['id'] == recipient_id), None)
        if not rec:
            raise Bad('recipient not in the list')                      # the closed circle
        reg = self.docs.load()
        doc = reg['documents'].get(message_id)
        if not doc:
            raise Bad('only documents in the receipts register can be forwarded')
        if doc.get('kind') not in ('receipt', 'invoice', 'bill', 'credit', 'reminder', None):
            raise Bad('not a receipt/invoice')
        if self._sent_today(reg) >= DAILY_CAP:
            raise Bad(f'daily limit of {DAILY_CAP} forwards reached')
        if any(s.get('to') == rec['email'] for s in doc.get('sent', [])) and how == 'auto':
            return 'already sent'
        self.forward_fn(doc.get('account') or 'iCloud', message_id, rec['email'], rec['name'])
        with self.docs.lock:
            reg = self.docs.load()
            doc = reg['documents'][message_id]
            doc.setdefault('sent', []).append({'to': rec['email'], 'name': rec['name'], 'id': rec['id'], 'at': _now(), 'how': how})
            if how == 'manual':
                r = reg['vendor_rules'].setdefault(doc['vendor_key'], {'project': None, 'kind': None, 'count': 0})
                r.setdefault('forward', {})
                r['forward'][rec['id']] = r['forward'].get(rec['id'], 0) + 1
            self.docs.save(reg)
        return f"forwarded to {rec['name']}"

    def suggestion(self, reg, doc):
        """Most likely recipient for a document: vendor history first, then the recipient tied to its project."""
        rule = reg['vendor_rules'].get(doc.get('vendor_key'), {})
        hist = rule.get('forward') or {}
        if hist:
            return max(hist.items(), key=lambda kv: kv[1])[0]
        rec = next((r for r in self.load()['recipients'] if r.get('project') and r['project'] == doc.get('project')), None)
        return rec['id'] if rec else None

    def auto_once(self, log, audit=None):
        """Forward new, completed documents whose vendor has auto-forward switched on."""
        reg = self.docs.load()
        n = 0
        for mid, doc in list(reg['documents'].items()):
            rule = reg['vendor_rules'].get(doc.get('vendor_key'), {})
            auto = rule.get('auto_forward')
            if not auto or doc.get('needs_details') or doc.get('hidden'):
                continue
            if (doc.get('added') or '') < auto.get('since', '9999'):
                continue                                            # only documents that arrive after it was switched on
            if any(s.get('id') == auto['recipient'] for s in doc.get('sent', [])):
                continue
            try:
                self.forward(mid, auto['recipient'], how='auto')
                n += 1
                log.write(f"{_now()} auto-forward: {doc.get('vendor')} {mid[:30]} → {auto['recipient']}\n")
                if audit:
                    audit('auto_forward', '%s → %s' % (doc.get('vendor') or 'receipt', auto['recipient']))
            except Exception as e:
                log.write(f'auto-forward failed: {str(e)[:200]}\n')
        return n

    # ---------- dashboard ----------
    def action(self, action, p):
        if action == 'recipients_set':
            out = []
            for r in p.get('recipients') or []:
                name = str(r.get('name', '')).strip()[:80]
                email = str(r.get('email', '')).strip()[:200]
                if not name or not EMAIL.match(email):
                    raise Bad(f'bad recipient: {name or email}')
                out.append({'id': r.get('id') or 'r' + secrets.token_hex(4), 'name': name, 'email': email,
                            'project': r.get('project') or None})
            with LOCK:
                self._save({'recipients': out[:30]})
            return 'saved'
        if action == 'document_forward':
            return self.forward(str(p.get('message_id', '')), str(p.get('recipient', '')))
        if action == 'vendor_auto_forward':
            key, rid = str(p.get('vendor_key', '')), p.get('recipient')
            with self.docs.lock:
                reg = self.docs.load()
                rule = reg['vendor_rules'].setdefault(key, {'project': None, 'kind': None, 'count': 0})
                if rid:
                    if rid not in [r['id'] for r in self.load()['recipients']]:
                        raise Bad('recipient not in the list')
                    if (rule.get('forward') or {}).get(rid, 0) < AUTO_AFTER:
                        raise Bad(f'forward this vendor to that recipient {AUTO_AFTER}× by hand first')
                    rule['auto_forward'] = {'recipient': rid, 'since': _now()}
                else:
                    rule.pop('auto_forward', None)
                self.docs.save(reg)
            return 'saved'
        raise Bad('unknown action')
