from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class Command(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: str = Field(min_length=8, max_length=128, pattern=r'^[a-zA-Z0-9_-]+$')
    operation: Literal['send','queue','steer','interrupt','approval','clarify']
    payload: dict = Field(default_factory=dict)


def validate_payload(operation, payload):
    from .security import require
    keys = {
        'send': {'text','attachment_ids'}, 'queue': {'text','attachment_ids'}, 'steer': {'text'},
        'interrupt': set(), 'approval': {'pending_request_id','choice'},
        'clarify': {'pending_request_id','answer','answers'},
    }
    require(set(payload) <= keys[operation], 400, 'Unknown operation payload fields')
    if operation in {'send','queue','steer'}:
        text = payload.get('text','')
        require(isinstance(text,str) and 0 < len(text.strip()) <= 60000, 400, 'Text must be 1–60000 characters')
        ids = payload.get('attachment_ids', [])
        require(isinstance(ids,list) and len(ids)<=5 and all(isinstance(x,str) for x in ids), 400, 'Invalid attachments')
    if operation in {'approval','clarify'}:
        require(isinstance(payload.get('pending_request_id'),str), 400, 'Pending request required')
    if operation == 'approval':
        require(payload.get('choice') in {'once','session','always','deny'}, 400, 'Invalid choice')
    if operation == 'clarify':
        require(('answer' in payload) != ('answers' in payload), 400, 'Choose answer or answers')
        answer = payload.get('answer',payload.get('answers'))
        require(isinstance(answer,str) or (isinstance(answer,dict) and all(isinstance(v,str) for v in answer.values())), 400, 'Invalid answer')


def receipt_public(row):
    return {key: row.get(key) for key in ('request_id','state','result','error')}
