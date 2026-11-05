"""One way to change a digest file after its run wrote it (scam check, Always hold, Mark safe, subscriptions line,
digest scope): lock it, read it again inside the lock, apply the change, write it atomically. Two passes on the same
file can then never overwrite each other's change.

    digestfile.update(path, fn)   fn(d) -> (write: bool, result); returns result (None when the file can't be read)

The lock is fcntl.flock on "<path>.lock" (housekeeping removes old lock files). Python 3.9.
"""
import fcntl
import json
import os
import threading


def update(path, fn):
    with open(path + '.lock', 'a') as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        os.utime(path + '.lock')                 # "in use" for housekeeping's prune
        try:
            try:
                with open(path, encoding='utf-8') as f:
                    d = json.load(f)
            except (OSError, ValueError):
                return None
            write, result = fn(d)
            if write:
                tmp = '%s.%d-%d.tmp' % (path, os.getpid(), threading.get_ident())
                with open(tmp, 'w', encoding='utf-8') as f:
                    json.dump(d, f, ensure_ascii=False, indent=1)
                os.replace(tmp, path)
            return result
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)
