"""Audio for Listen: the spoken digest and briefs turned into sound files on the Mac mini (macOS `say`), so the phone
plays real audio – which keeps playing with the screen locked and shows play/pause/next on the lock screen, the
steering wheel and CarPlay (the browser's own speech stops when the screen locks).

Files: state/audio/<hash>.m4a – one per spoken text and voice, made on first request, removed after 7 days.
The voice per language is picked from the voices installed on this Mac (Settings → Accessibility → Spoken Content →
System voice → Manage voices to add better ones; Premium/Enhanced voices are preferred when present).
"""
import glob
import hashlib
import os
import re
import subprocess
import tempfile
import threading
import time

SAY = '/usr/bin/say'
KEEP_DAYS = 7
PREFER = {
    'da': ['Sara (Premium)', 'Sara (Enhanced)', 'Magnus (Premium)', 'Magnus (Enhanced)', 'Sara', 'Magnus'],
    'en': ['Zoe (Premium)', 'Ava (Premium)', 'Jamie (Premium)', 'Serena (Premium)', 'Samantha (Enhanced)',
           'Daniel (Enhanced)', 'Serena', 'Samantha', 'Daniel', 'Karen'],
}
_LOCK = threading.Lock()
_VOICES = {'at': 0, 'list': []}
DA = re.compile(r'\b(og|ikke|det|der|jeg|har|til|med|på|en|et|af|for|er)\b', re.I)


class AudioError(Exception):
    pass


def available():
    return os.path.exists(SAY)


def language(text):
    words = len(text.split()) or 1
    return 'da' if len(DA.findall(text)) / words > 0.08 else 'en'


def voices():
    if time.time() - _VOICES['at'] > 3600:
        try:
            out = subprocess.run([SAY, '-v', '?'], capture_output=True, text=True, timeout=15).stdout
            _VOICES['list'] = [re.split(r'\s{2,}', ln.strip())[0] for ln in out.splitlines() if ln.strip()]
        except (OSError, subprocess.TimeoutExpired):
            _VOICES['list'] = []
        _VOICES['at'] = time.time()
    return _VOICES['list']


def voice_for(lang):
    have = voices()
    for v in PREFER.get(lang, PREFER['en']):
        if v in have:
            return v
    return None                                   # the system voice


def render(state_dir, text, lang=None):
    """Path of an .m4a with `text` read aloud (made once, then cached)."""
    if not available():
        raise AudioError('macOS speech (say) is not available')
    text = re.sub(r'https?://\S+', '', str(text or '')).strip()[:20000]
    if not text:
        raise AudioError('nothing to read')
    lang = lang if lang in ('da', 'en') else language(text)
    v = voice_for(lang)
    d = os.path.join(state_dir, 'audio')
    os.makedirs(d, exist_ok=True)
    out = os.path.join(d, hashlib.sha256(('%s|%s' % (v, text)).encode()).hexdigest()[:24] + '.m4a')
    if os.path.exists(out) and os.path.getsize(out) > 0:
        os.utime(out)
        return out
    with _LOCK:                                   # one `say` at a time – the Mac mini has other work too
        if os.path.exists(out) and os.path.getsize(out) > 0:
            return out
        with tempfile.NamedTemporaryFile('w', suffix='.txt', dir=d, delete=False, encoding='utf-8') as f:
            f.write(text)
            src = f.name
        tmp = out + '.part.m4a'
        try:
            cmd = [SAY, '-r', '180', '-o', tmp, '--file-format=m4af', '--data-format=aac', '-f', src]
            if v:
                cmd[1:1] = ['-v', v]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=60 + len(text) // 40)
            if r.returncode != 0 or not os.path.exists(tmp) or not os.path.getsize(tmp):
                raise AudioError('say failed: ' + (r.stderr or 'no output').strip()[:200])
            os.replace(tmp, out)
        except subprocess.TimeoutExpired:
            raise AudioError('say took too long')
        finally:
            for p in (src, tmp):
                try:
                    os.remove(p)
                except OSError:
                    pass
        prune(d)
    return out


def prune(d):
    cutoff = time.time() - KEEP_DAYS * 86400
    for p in glob.glob(os.path.join(d, '*.m4a')):
        try:
            if os.path.getmtime(p) < cutoff:
                os.remove(p)                      # our own cache files, made again on demand
        except OSError:
            pass
