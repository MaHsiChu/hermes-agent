"""Credential stays server-side; MCP and the Hermes plugin call this local client."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import portalocker

ROOT=Path(__file__).resolve().parent
SETTINGS=json.loads((ROOT/'settings.json').read_text(encoding='utf-8'))
DATA=ROOT/'data'
DATA.mkdir(exist_ok=True)


def request(op,body=None):
    token=(DATA/'token').read_text(encoding='ascii')
    req=Request(f'http://127.0.0.1:{SETTINGS["port"]}/rpc/{op}',data=json.dumps(body or {}).encode(),headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'},method='POST')
    try:
        with urlopen(req,timeout=45) as resp: return json.load(resp)
    except HTTPError as exc:
        raise ValueError(exc.read().decode('utf-8','replace')) from exc


def ensure():
    try: return request('health')
    except (OSError,ValueError): pass
    with portalocker.Lock(str(DATA/'startup.lock'),timeout=20):
        try: return request('health')
        except (OSError,ValueError): pass
        with (DATA/'service.log').open('ab') as log:
            subprocess.Popen([sys.executable,str(ROOT/'service.py')],cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=log,creationflags=(subprocess.CREATE_NO_WINDOW|subprocess.CREATE_NEW_PROCESS_GROUP) if os.name=='nt' else 0)
        for _ in range(80):
            time.sleep(.15)
            try: return request('health')
            except (OSError,ValueError): pass
    raise RuntimeError('Session Hub did not start; inspect extensions/session-hub/data/service.log')


def call(op,body=None):
    ensure()
    return request(op,body)


if __name__=='__main__':
    print(json.dumps(call(sys.argv[1] if len(sys.argv)>1 else 'health',json.loads(sys.argv[2]) if len(sys.argv)>2 else {}),ensure_ascii=False,indent=2))
