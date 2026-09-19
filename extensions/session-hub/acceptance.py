"""Live acceptance uses only newly created disposable development sessions."""
import json
from pathlib import Path
import time
import uuid
from client import call

BASE=Path(__file__).resolve().parents[2]
run=uuid.uuid4().hex[:8]
results=[]

def wait(jid):
    deadline=time.monotonic()+240
    while time.monotonic()<deadline:
        job=call('jobs',{'job_id':jid})['jobs'][0]
        if job['state'] not in ('queued','checking','running','waiting_handoff'): return job
        time.sleep(2)
    raise TimeoutError(jid)

for engine in ('claude','codex'):
    cwd=BASE/'playground/session-hub-acceptance'/run/engine
    cwd.mkdir(parents=True)
    secret=f'{engine.upper()}-{run}'
    first=call('dispatch',{'engine':engine,'cwd':str(cwd),'mode':'workspace-write','request_key':run+'-'+engine+'-new','prompt':f'This is a local connection acceptance test. Remember the session marker {secret}. Create only proof.txt in the current directory with the exact contents {secret}. Do not modify any other files. Return a concise confirmation.'})
    a=wait(first['id'])
    assert a['state']=='completed',(engine,a['state'],a['detail'],a['answer'])
    assert (cwd/'proof.txt').read_text(encoding='utf-8').strip()==secret,(engine,'file content mismatch')
    call('watch',{'engine':engine,'session_id':a['session_id']})
    second=call('dispatch',{'engine':engine,'session_id':a['session_id'],'mode':'read-only','request_key':run+'-'+engine+'-resume','prompt':'What session marker did I tell you in the previous message? Reply with just that marker. Do not use any tools.'})
    b=wait(second['id'])
    assert b['state']=='completed' and b['session_id']==a['session_id'] and secret in b['answer'],(engine,b)
    results.append({'engine':engine,'session_id':a['session_id'],'new_job':a['id'],'resume_job':b['id'],'file_write':True,'same_session_resume':True,'answer':b['answer']})
    print(json.dumps(results[-1],ensure_ascii=False),flush=True)
time.sleep(6)
events=call('events',{'recent':True})['events']
for result in results:
    assert any(e['kind']=='external_turn_completed' and e['session_id']==result['session_id'] for e in events),'watch completion missing'
record={'run':run,'results':results,'completion_inbox':True,'watched_native_completion':True}
(Path(__file__).parent/'acceptance-results.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
print('Live acceptance passed',flush=True)
