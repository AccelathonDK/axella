#!/usr/bin/env python3
"""Mail HTML sanitiser (security review 3, P3-1) and the dashboard's content policy. Fictional HTML only.
Run: python3 setup/tests/test_mail_html.py"""
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import mailsearch as M  # noqa: E402

fails = 0


def ok(c, label):
    global fails
    print(('  ok   ' if c else '  FAIL ') + label)
    fails += 0 if c else 1


def clean(h, pics=False):
    return M.sanitize(h, {'logo1': 'data:image/png;base64,AAAA'}, pics)[0]


def no_remote(out):
    """No address the browser would fetch on its own, other than the proxy and inline pictures."""
    urls = re.findall(r'(?i)(?:src|background|poster|srcset)\s*=\s*"([^"]*)"|url\("([^"]*)"\)', out)
    return all(u.startswith(('data:image/', 'about:blank', '/axella/api/img?')) or not u for pair in urls for u in pair) \
        and 'http' not in re.sub(r'href="[^"]*"', '', out).replace('/axella/api/img?u=http', '')


cases = {
    'script': '<p>hi</p><script>alert(1)</script>',
    'event handler': '<img src="cid:logo1" onerror="alert(1)">',
    'javascript: link': '<a href="javascript:alert(1)">x</a>',
    'entity-encoded scheme': '<a href="&#x6A;avascript:alert(1)">x</a>',
    'tab inside scheme': '<a href="java\tscript:alert(1)">x</a>',
    'srcset': '<img srcset="https://t.example/p.png 1x" src="cid:logo1">',
    'video poster': '<video poster="https://t.example/p.png"></video>',
    'input type=image': '<input type="image" src="https://t.example/p.png">',
    'protocol-relative css url': '<div style="background:url(//t.example/p.png)">x</div>',
    'escaped css url': '<div style="background:u\\72l(https://t.example/p.png)">x</div>',
    'css @import': '<style>@import url(https://fonts.googleapis.com/css?family=X); p{color:red}</style>',
    'css image-set': '<div style="background-image:image-set(\'https://t.example/p.png\' 1x)">x</div>',
    'unterminated url(': '<style>p{background:url(https://t.example/p.png</style>',
    'link/meta/base': '<link rel="stylesheet" href="https://t.example/s.css"><meta http-equiv="refresh" content="0;url=https://t.example"><base href="https://t.example/">',
    'iframe': '<iframe src="https://t.example"></iframe>',
    'svg': '<svg><image href="https://t.example/p.png"/></svg>',
    'form': '<form action="https://t.example"><input name="pw"></form>',
    'remote img': '<img src="https://t.example/p.png">',
    'background attribute': '<table background="https://t.example/p.png"><tr><td>x</td></tr></table>',
}
for name, h in cases.items():
    out = clean(h)
    bad = re.search(r'(?i)<(script|iframe|svg|form|input|link|meta|base|video)\b|on\w+=|javascript:|srcset|poster|@import', out)
    ok(not bad and no_remote(out), name + ('' if not bad and no_remote(out) else ' → ' + out))

out = clean('<p>Hello <b>Lee</b> &amp; <a href="https://acme.example/x?a=1&amp;b=2">report</a></p><img src="cid:logo1">')
ok('<b>Lee</b>' in out and 'href="https://acme.example/x?a=1&amp;b=2"' in out and 'data:image/png;base64,AAAA' in out,
   'ordinary mail keeps text, links and inline pictures')
r = M.sanitize('<img src="https://t.example/p.png">', {}, True)
ok(r[1] and '/axella/api/img?u=https%3A%2F%2Ft.example%2Fp.png&amp;k=' in r[0], 'with pictures on: remote picture goes through the signed proxy')
ok(M.sanitize('<img src="https://t.example/p.png">')[1] and not M.sanitize('<p>x</p>')[1], 'remote pictures are detected')

# the dashboard's own content policy is the second wall: it must stay in index.html
idx = os.path.join(os.path.dirname(HERE), 'web', 'index.html')
if os.path.exists(idx):
    page = open(idx, encoding='utf-8').read()
    csp = re.search(r'http-equiv="Content-Security-Policy"\s+content="([^"]+)"', page)
    ok(bool(csp) and "img-src 'self' data: blob:" in csp.group(1) and 'fonts.googleapis.com' not in csp.group(1),
       'web/index.html keeps its CSP (pictures only from itself, no Google Fonts)')
print('PASS' if not fails else 'FAIL (%d)' % fails)
sys.exit(1 if fails else 0)
