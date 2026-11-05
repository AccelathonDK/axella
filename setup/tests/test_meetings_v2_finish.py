#!/usr/bin/env python3
"""Meeting prep v2, finish (setup/meetings.py, axella-actions.py): the transcription status and its line on Runs,
a recording uploaded in chunks (a lost answer, a gap, resume, finish, drop), Rename speakers, Add from project,
outcomes back into the points, and a follow-up to several recipients in Axella's composer (read back before Mail
sends). Invented meetings, people and texts only. Run: python3 setup/tests/test_meetings_v2_finish.py"""
import importlib.util
import io
import os
import stat
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import meetings as M  # noqa: E402

fails = 0


def ok(c, label):
    global fails
    print(('  ok   ' if c else '  FAIL ') + label)
    fails += 0 if c else 1


def bad(fn, label):
    try:
        fn()
        ok(False, label)
    except M.Bad:
        ok(True, label)


tmp = tempfile.mkdtemp()
st = os.path.join(tmp, 'state')
os.makedirs(st)

# ---- the transcription status (config, the defaults)
binp, model = os.path.join(tmp, 'whisper-cli'), os.path.join(tmp, 'ggml-large-v3-turbo.bin')
ok(M.Transcriber({'whisper_bin': binp, 'whisper_model': model}).status()['transcribe'] is False, 'not installed: not set up')
open(binp, 'w').write('#!/bin/sh\n')
os.chmod(binp, stat.S_IRWXU)
s = M.Transcriber({'whisper_bin': binp, 'whisper_model': model}).status()
ok(not s['transcribe'] and 'model' in s['why'], 'whisper but no model: says so')
open(model, 'wb').write(b'x')
s = M.Transcriber({'whisper_bin': binp, 'whisper_model': model, 'language': 'da'}).status()
ok(s['transcribe'] and s['model'] == 'ggml-large-v3-turbo.bin' and s['language'] == 'da' and s['configured'], 'set up: model and language from the config')


class Run:
    def __init__(self, text):
        self.text = text

    def __call__(self, cmd, **kw):
        class R:
            returncode, stdout, stderr = 0, '', ''
        if '-of' in cmd:
            open(cmd[cmd.index('-of') + 1] + '.txt', 'w').write(self.text)
        else:                                   # the conversion: an invented 2 min wav (16 kHz mono 16-bit)
            out = cmd[-1] if cmd[0].endswith('afconvert') else cmd[-1]
            open(out, 'wb').write(b'\0' * (44 + 32000 * 120))
        return R()


notes = []
tr = M.Transcriber({'whisper_bin': binp, 'whisper_model': model}, run=Run('Speaker 1: Hello all.\nSpeaker 2: Hi.\nSpeaker 1: Shall we start?\nSpeaker 2: Yes.'),
                   note=lambda *a: notes.append(a))
M.Transcriber._wav = lambda self, src, t: (open(os.path.join(t, 'in.wav'), 'wb').write(b'\0' * (44 + 32000 * 120)), os.path.join(t, 'in.wav'))[1]
src = os.path.join(tmp, 'clip.m4a')
open(src, 'wb').write(b'invented')
text = tr.transcribe(src)
ok(text.startswith('Speaker 1: Hello all.'), 'transcribed on the Mac mini')
ok(notes and notes[0][0] == 'done' and notes[0][1].startswith('2 min of audio · ggml-large-v3-turbo.bin · ') and 'Hello' not in str(notes),
   'a line on Runs: length, model and duration – never the text')

# ---- a recording uploaded as it is made
W = M.Meetings(st, os.path.join(st, 'deleted', 'meetings'))
mid = W.action('meeting_add', {'title': 'Acme planning', 'attendees': [{'name': 'Lee Chen', 'email': 'lee@example.com'}, {'name': 'Sam Rivera', 'email': ''}],
                               'points': [{'text': 'Budget for the launch'}, {'text': 'Who writes the brief'}]})['id']
rid = 'r' + 'a1' * 6
chunk = lambda seq, data, ctype='audio/webm': W.record_chunk(mid, rid, seq, ctype, io.BytesIO(data).read, len(data))
r0 = chunk(0, b'AAAA')
r1 = chunk(1, b'BBBB')
ok(r1['next'] == 2 and r1['bytes'] == 8, 'chunks are stored in order as they arrive')
ok(chunk(1, b'BBBB').get('repeat') and W.get(mid)['recordings'][rid]['bytes'] == 8, 'a chunk sent again (a lost answer) is taken once')
bad(lambda: chunk(3, b'DDDD'), 'a gap is refused (the phone resends from the missing chunk)')
bad(lambda: W.record_chunk(mid, '../x', 0, 'audio/webm', io.BytesIO(b'x').read, 1), 'a bad recording id is refused')
bad(lambda: W.record_chunk(mid, 'r' + 'b2' * 6, 0, 'text/html', io.BytesIO(b'x').read, 1), 'only audio')
ok(W.get(mid)['recordings'][rid]['bytes'] == 8, 'cut off (no finish): what arrived is kept on the prep')
done = W.record_finish(mid, rid, 'Recording 10:12', tr, start=lambda target, args, daemon: type('T', (), {'start': lambda self: target(*args)})())
m = W.get(mid)
x = next(y for y in m['materials'] if y['id'] == done['id'])
ok(rid not in m.get('recordings', {}) and x['audio'] and x['size'] == 8 and x['status'] == 'ready', 'Finish: the recording becomes a material and is transcribed')
ok(open(os.path.join(W._dir(mid), x['id'] + '.webm'), 'rb').read() == b'AAAABBBB', '… the whole recording, in order')
rid2 = 'r' + 'c3' * 6
W.record_chunk(mid, rid2, 0, 'audio/mp4', io.BytesIO(b'xx').read, 2)
W.record_drop(mid, rid2)
ok(rid2 not in W.get(mid).get('recordings', {}), 'Drop: a kept recording you don\'t want is removed')

# ---- Rename speakers
ok(M.speakers_of(text) == ['Speaker 1', 'Speaker 2'], 'speaker labels found in the transcript')
ok(M.speakers_of('Lee Chen: hi\nSam Rivera: hello\nLee Chen: so') == ['Lee Chen'], 'a Teams/Zoom name label counts when it starts two lines')
W.action('meeting_speakers', {'id': mid, 'material': x['id'], 'names': {'Speaker 1': 'Lee Chen', 'Speaker 2': 'Alex Example'}, '_owner': 'Alex Example'})
t2 = W.material_text(mid, x['id'])
ok(t2.startswith('Lee Chen: Hello all.') and 'Alex Example: Hi.' in t2, 'the names are used in the text (Find outcomes reads this)')
ok(W._raw_text(mid, x['id']).startswith('Speaker 1:'), '… the stored transcript keeps its own labels')
bad(lambda: W.action('meeting_speakers', {'id': mid, 'material': x['id'], 'names': {'Speaker 1': 'Someone Else'}, '_owner': 'Alex Example'}),
    'only a name from the meeting\'s people')
bad(lambda: W.action('meeting_speakers', {'id': mid, 'material': x['id'], 'names': {'Speaker 9': 'Lee Chen'}, '_owner': 'Alex Example'}), 'only labels in the transcript')

# ---- Add from project (by reference)
PROJ = {('pr1', 'note', 'n1'): 'Launch is in May. Budget 10.', ('pr1', 'file', 'f1'): 'Brief draft text'}
W.project_text = lambda pid, kind, ref: PROJ.get((pid, kind, ref))
W.action('meeting_project_add', {'id': mid, 'project': 'pr1', 'kind': 'note', 'ref': 'n1', 'name': 'Launch note'})
mat = next(y for y in W.get(mid)['materials'] if y['kind'] == 'project')
ok(mat['ref'] == 'n1' and W.material_text(mid, mat['id']) == 'Launch is in May. Budget 10.', 'a project note as a material, read from the project')
PROJ[('pr1', 'note', 'n1')] = 'Launch moved to June.'
ok(W.material_text(mid, mat['id']) == 'Launch moved to June.', '… by reference: the project keeps the original')
bad(lambda: W.action('meeting_project_add', {'id': mid, 'project': 'pr1', 'kind': 'note', 'ref': 'n1'}), 'not twice')
bad(lambda: W.action('meeting_project_add', {'id': mid, 'project': 'pr1', 'kind': 'note', 'ref': 'gone'}), 'not one that isn\'t in the project')

# ---- outcomes back into the points
W.action('meeting_update', {'id': mid, 'outcomes': {'summary': '', 'items': [{'kind': 'decision', 'text': 'Budget is 10'}, {'kind': 'fact', 'text': 'x'}]}})
oc = W.get(mid)['outcomes']['items']
pt = W.get(mid)['points'][0]
W.action('meeting_point_outcome', {'id': mid, 'point': pt['id'], 'outcome': oc[0]['id']})
pt = W.get(mid)['points'][0]
ok(pt['done'] and pt['outcome']['text'] == 'Budget is 10', 'a decision ticks the point it answers, with its outcome')
W.action('meeting_update', {'id': mid, 'points': W.get(mid)['points']})
ok(W.get(mid)['points'][0].get('outcome'), '… and it stays when the points are saved again')
bad(lambda: W.action('meeting_point_outcome', {'id': mid, 'point': pt['id'], 'outcome': oc[1]['id']}), 'only a decision or a task')
W.action('meeting_point_outcome', {'id': mid, 'point': pt['id'], 'outcome': None})
ok(not W.get(mid)['points'][0]['done'] and 'outcome' not in W.get(mid)['points'][0], '… and can be taken back')

# ---- the follow-up to several recipients in Axella's composer
spec = importlib.util.spec_from_file_location('axa', os.path.join(HERE, 'axella-actions.py'))
A = importlib.util.module_from_spec(spec)
spec.loader.exec_module(A)
ok(A.new_recipients('lee@example.com, sam@example.net;lee@example.com') == ['lee@example.com', 'sam@example.net'], 'several recipients, each once')
for v in ('Lee <lee@example.com>', 'noreply@example.com', 'not an address'):
    try:
        A.new_recipients(v)
        ok(False, 'refused: %s' % v)
    except A.Bad:
        ok(True, 'refused: %s' % v)
calls = []
A.SENT_FILE = os.path.join(tmp, 'sent.json')
A.config = lambda: {'accounts': {'iCloud': {'kind': 'private', 'address': 'alex@example.com'}}}
A.osa = lambda script, *args, **kw: (calls.append((script, args)), 'sent')[1]
A.mail_accounts = lambda: {'iCloud': 'iCloud'}
try:
    A.do_action('mail_send', {'account': 'iCloud', 'to': 'lee@example.com, sam@example.net', 'cc': 'kim@example.org', 'subject': 'Follow-up',
                              'text': 'Thanks all.', 'confirm': 'send', '_login': 'owner@example.com'})
    sc, args = calls[-1]
    ok(sc is A.SEND_NEW_MULTI_SCRIPT and args[1] == 'lee@example.com\x1esam@example.net' and args[2] == 'kim@example.org'
       and args[6] == 'to:lee@example.com\x1eto:sam@example.net\x1ecc:kim@example.org\x1e', 'several recipients: set, then read back and compared before Mail sends')
except Exception as e:
    ok(False, 'several recipients: %s' % e)
ok(M.audio_len(20) == 'under 1 min' and M.audio_len(0) == 'under 1 min' and M.audio_len(90) == '2 min' and M.audio_len(None) == 'under 1 min',
   'the Runs line: a short clip says "under 1 min", never "0 min of audio"')
print('%d failed' % fails if fails else 'all ok')
sys.exit(1 if fails else 0)
