"""Exercise the actual Hermes backend route with a private test bearer token."""
import os
from pathlib import Path
import secrets
import sys
BASE=Path(__file__).resolve().parents[2]
if not os.environ.get('HERMES_HOME'): raise SystemExit('Set HERMES_HOME to the explicitly configured test profile before this live check.')
token=secrets.token_urlsafe(32)
os.environ['HERMES_DASHBOARD_SESSION_TOKEN']=token
sys.path.insert(0,str(BASE))
from hermes_cli.web_server import app
from fastapi.testclient import TestClient
client=TestClient(app,base_url='http://127.0.0.1')
response=client.post('/api/plugins/session-hub/rpc/health',json={},headers={'Authorization':'Bearer '+token})
print('Hermes plugin route HTTP status:',response.status_code)
assert response.status_code==200,response.text[:500]
assert response.json()['ok'] is True
response=client.post('/api/plugins/session-hub/rpc/sessions',json={'query':'connection','limit':2},headers={'Authorization':'Bearer '+token})
assert response.status_code==200,response.text[:500]
print('Hermes plugin API integration passed')
