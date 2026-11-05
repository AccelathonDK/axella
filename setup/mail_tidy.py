"""Keep Mail tidy (dev request keep-mail-tidy): what you handle in Axella is read in Mail.

Opening a mail in Axella's reader, filing it, Done, Delete (Trash) and sending a reply mark that mail read in Mail;
Undo marks it unread again. Only Mail – Messages, WhatsApp and Signal are never marked read (that would send a read
receipt). Only on the owner's own taps: the Claude runs still can't change read state (scheduler.py's never list).

The marks are collected here and run as one internal job in the action service's own job queue ("mail_mark"), up to
BATCH at a time, so they never run beside another Mail script and never block the dashboard. A mail with a private or
hidden contact is never touched (checked again when the batch runs; if the mail's file can't be found, it is skipped –
fails closed). A mail Mail can't find any more (moved by hand, deleted) is skipped quietly and noted in the log.
AppleScript gets the account and Message-ID only as argv."""
import collections
import re
import sys
import threading

BATCH = 20
MID = re.compile(r'^[^\s\x00-\x1f]{3,500}$')

MARK_SCRIPT_RUN = '''
on run argv
  set out to ""
  repeat with i from 1 to (count of argv) by 3
    set st to item i of argv
    try
      set m to my findMessage(item (i + 1) of argv, item (i + 2) of argv)
      tell application "Mail" to set read status of m to (st is "read")
      set out to out & "ok" & linefeed
    on error
      set out to out & "missing" & linefeed
    end try
  end repeat
  return out
end run
'''


class Tidy:
    """mark(account, mid, read) from the action handlers; run() from the job worker."""

    def __init__(self, osa, find_message, allowed, enqueue, log=sys.stderr):
        self.osa = osa                    # axella-actions.osa (argv only)
        self.script = find_message + MARK_SCRIPT_RUN
        self.allowed = allowed            # (account, mid) -> True when the mail may be touched (no private contact)
        self.enqueue = enqueue            # puts one "mail_mark" job in the job queue
        self.log = log
        self.lock = threading.Lock()
        self.pending = collections.OrderedDict()   # (account, mid) -> True (read) / False (unread); the last tap wins
        self.queued = False

    def mark(self, account, mid, read=True):
        account, mid = str(account or ''), str(mid or '').strip()
        if not account or not MID.match(mid):
            return False
        with self.lock:
            self.pending.pop((account, mid), None)
            self.pending[(account, mid)] = bool(read)
            if self.queued:
                return True
            self.queued = True
        try:
            self.enqueue()
        except Exception as e:
            with self.lock:
                self.queued = False
            self.log.write('mail tidy: not queued: %s\n' % str(e)[:200])
            return False
        return True

    def run(self):
        """One batch (the job worker). Returns counts only – never subjects or addresses."""
        with self.lock:
            batch = []
            while self.pending and len(batch) < BATCH:
                batch.append(self.pending.popitem(last=False))
            more = bool(self.pending)
            self.queued = more
        if more:
            try:
                self.enqueue()
            except Exception:
                with self.lock:
                    self.queued = False
        args, skipped = [], 0
        for (account, mid), read in batch:
            try:
                ok = self.allowed(account, mid)
            except Exception:
                ok = False
            if not ok:
                skipped += 1
                continue
            args += ['read' if read else 'unread', account, mid]
        done = missing = 0
        if args:
            n = len(args) // 3
            try:
                out = self.osa(self.script, *args, timeout=60 + 30 * n)
            except Exception as e:
                self.log.write('mail tidy: %d not marked: %s\n' % (n, str(e)[:200]))
                return {'marked': 0, 'missing': 0, 'skipped': skipped, 'failed': n}
            lines = [x.strip() for x in str(out).split('\n') if x.strip()]
            done = sum(1 for x in lines if x == 'ok')
            missing = n - done
        if missing:
            self.log.write('mail tidy: %d mail%s not found in Mail (moved or deleted) – skipped\n' % (missing, '' if missing == 1 else 's'))
        return {'marked': done, 'missing': missing, 'skipped': skipped, 'failed': 0}
