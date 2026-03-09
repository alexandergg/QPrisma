#!/usr/bin/env bash
set -euo pipefail

python -c "import json,re,sys
raw=sys.stdin.read()
try:
    payload=json.loads(raw) if raw.strip() else {}
except Exception:
    payload={}
tool=str(payload.get('toolName',''))
tool_args=payload.get('toolArgs','')
command=''
if isinstance(tool_args,str):
    try:
        parsed=json.loads(tool_args)
        command=str(parsed.get('command',''))
    except Exception:
        command=tool_args
else:
    command=str(tool_args)
text=(tool+' '+command).lower()
patterns=[
    r'git\\s+reset\\s+--hard',
    r'git\\s+checkout\\s+--',
    r'rm\\s+-rf\\s+/',
    r'format\\s+[a-z]:',
    r'drop\\s+table'
]
blocked=any(re.search(p,text) for p in patterns)
if blocked:
    print(json.dumps({'permissionDecision':'deny','permissionDecisionReason':'Blocked by QPrisma Copilot guardrail policy'}))
else:
    print(json.dumps({'permissionDecision':'allow'}))
"
