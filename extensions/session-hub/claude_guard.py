"""Fail closed unless the relay sends the exact user task to the selected peer."""
import json
from pathlib import Path
import sys


def validate(spec,tool):
    recipient=tool.get('to')
    content=tool.get('message')
    if recipient!=spec['name'] or content!=spec['message']:
        return 'Relay must preserve the exact selected recipient and message.'
    if tool.get('type','message')!='message': return 'Only a text message is authorized.'
    from claude_live import sessions
    peers=[p for p in sessions() if p['title']==spec['name']]
    if len(peers)!=1 or peers[0]['session_id']!=spec['session_id']:
        return 'Selected live peer changed or its name is ambiguous; refresh sessions.'
    return ''


if __name__=='__main__':
    try:
        spec=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
        request=json.load(sys.stdin)
        tool=request.get('tool_input',{})
        Path(sys.argv[1]+'.tool.json').write_text(json.dumps(tool,ensure_ascii=False),encoding='utf-8')
        reason=validate(spec,tool)
        if not reason:
            # At most one permitted send per submission, even if the relay retries.
            with Path(sys.argv[1]+'.claimed').open('x') as f:f.write('claimed before send')
    except Exception as e: reason=str(e)
    if reason:
        print(json.dumps({'hookSpecificOutput':{'hookEventName':'PreToolUse','permissionDecision':'deny','permissionDecisionReason':reason}}))
    # No allow override: the target's normal inbound controls still apply.
