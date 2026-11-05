#!/usr/bin/env python3
"""Live check of setup/mcp_filter.py on the Mac mini: starts the real Macuse behind the filter and asks only for the
handshake and the list of tools – no mail, messages or calendar are read. Run: python3 setup/tests/test_mcp_filter_live.py"""
import json
import os
import subprocess
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
p = subprocess.Popen([sys.executable, os.path.join(BASE, 'setup', 'mcp_filter.py'), os.path.join(BASE, 'state', 'mcp.json')],
                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
send = lambda m: (p.stdin.write(json.dumps(m) + '\n'), p.stdin.flush())
send({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-03-26', 'capabilities': {},
      'clientInfo': {'name': 'axella-filter-test', 'version': '1'}}})
start, got = time.time(), {}
while time.time() - start < 60 and 2 not in got:
    line = p.stdout.readline()
    if not line:
        break
    try:
        m = json.loads(line)
    except ValueError:
        continue
    if m.get('id') == 1 and 1 not in got:
        got[1] = m
        send({'jsonrpc': '2.0', 'method': 'notifications/initialized'})
        send({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'})
    elif m.get('id') == 2:
        got[2] = m
p.kill()
ok1 = 'result' in got.get(1, {})
tools = [t.get('name') for t in (got.get(2, {}).get('result') or {}).get('tools', [])]
print('handshake through the filter:', 'PASS' if ok1 else 'FAIL')
print('tools listed:', len(tools), '| mail tools:', sum(1 for t in tools if str(t).startswith('mail_')),
      '| messages tools:', sum(1 for t in tools if str(t).startswith('messages_')))
print('PASS' if ok1 and tools else 'FAIL')
