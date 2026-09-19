from pathlib import Path
import importlib.util
from fastapi import APIRouter,HTTPException

# Installer writes the external extension root; no imports from Hermes internals.
root=Path(__file__).resolve().parents[1]
source=Path((root/'extension-root.txt').read_text(encoding='utf-8').strip())
spec=importlib.util.spec_from_file_location('hermes_session_hub_client',source/'client.py')
client=importlib.util.module_from_spec(spec)
spec.loader.exec_module(client)
router=APIRouter()

@router.post('/rpc/{operation}')
def invoke(operation:str,body:dict):
    try: return client.call(operation,body)
    except (ValueError,RuntimeError,OSError) as exc: raise HTTPException(400,str(exc))
