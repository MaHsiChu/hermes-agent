import hashlib
import json
import re
import secrets

from fastapi import HTTPException


def digest(value):
    raw = value if isinstance(value, str) else json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def token():
    return secrets.token_urlsafe(32)


def opaque():
    return secrets.token_hex(16)


SENSITIVE = re.compile(r"(?:password|secret|token|authorization|api[_-]?key|credential|cookie|system_prompt|model_config)", re.I)
BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
KEY = re.compile(r"[\w-]+")
SECRET_KEY = re.compile(r"api[_-]?key|password|token|secret",re.I)
VALUE = re.compile(r"[^\s,;&]+")


def redact_assignments(value):
    # Each key is consumed once; sensitivity is checked without overlapping
    # greedy prefixes/suffixes. Values skipped after replacement are disjoint.
    parts=[];copied=0
    for key in KEY.finditer(value):
        if key.start()<copied or not SECRET_KEY.search(key[0]):
            continue
        position=key.end()
        while position<len(value) and value[position].isspace():
            position+=1
        if position==len(value) or value[position] not in '=:':
            continue
        position+=1
        while position<len(value) and value[position].isspace():
            position+=1
        secret=VALUE.match(value,position)
        if secret:
            parts.extend((value[copied:position],'[redacted]'))
            copied=secret.end()
    parts.append(value[copied:])
    return ''.join(parts)


def redact(value):
    if isinstance(value, dict):
        return {k: redact(v) for k, v in value.items() if not SENSITIVE.search(k)}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return redact_assignments(BEARER.sub("Bearer [redacted]", value))
    return value


def require(condition, status=404, message="Not found"):
    if not condition:
        raise HTTPException(status, message)
