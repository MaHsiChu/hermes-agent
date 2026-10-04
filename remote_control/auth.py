import secrets
import time

from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, Request, HTTPException
from starlette.responses import RedirectResponse
from sqlalchemy import delete

from . import db
from .security import digest, token, require


def current(request: Request):
    configured(request)
    row = request.app.state.store.web_user(request.cookies.get("remote_session"))
    require(row, 401, "Login required")
    return row


def mutation(request: Request):
    user = current(request)
    require(request.headers.get('origin') == request.app.state.config.public_url, 403, "Origin rejected")
    require(secrets.compare_digest(request.headers.get('x-csrf-token', ''), user['csrf']), 403, "CSRF rejected")
    return user


def configured(request):
    require(request.app.state.config.oidc is not None, 503, "OIDC is not configured")


def router(config):
    routes = APIRouter()
    oauth = OAuth()
    if config.oidc:
        oauth.register('identity', client_id=config.oidc.client_id,
            client_secret=config.oidc.client_secret.read() if config.oidc.client_secret else None,
            server_metadata_url=config.oidc.issuer + '/.well-known/openid-configuration',
            client_kwargs={'scope':'openid profile', 'code_challenge_method':'S256',
                           'token_endpoint_auth_method':'client_secret_basic' if config.oidc.client_secret else 'none'},
            claims_options={'iss': {'essential': True, 'value': config.oidc.issuer}})

    @routes.get('/api/remote/me')
    async def me(request: Request):
        user = request.app.state.store.web_user(request.cookies.get('remote_session')) if config.oidc else None
        return {'user': {'id':user['user_id'], 'name':user['name']} if user else None,
                'csrf_token': user['csrf'] if user else None,
                'login_url':'/auth/login' if config.oidc else None}

    @routes.get('/auth/login')
    async def login(request: Request):
        configured(request)
        raw = token()
        request.scope['session'] = {}
        response = await oauth.identity.authorize_redirect(request, config.public_url + '/auth/callback')
        with request.app.state.store.transaction() as c:
            c.execute(delete(db.flows).where(db.flows.c.expires_at < time.time()))
            c.execute(db.flows.insert().values(hash=digest(raw), data=request.session, expires_at=time.time()+600))
        response.set_cookie('remote_oidc', raw, httponly=True, secure=not config.development,
                            samesite='lax', max_age=600, path='/auth')
        return response

    @routes.get('/auth/callback')
    async def callback(request: Request):
        configured(request)
        store = request.app.state.store
        with store.transaction() as c:
            row = store.one(db.flows, db.flows.c.hash == digest(request.cookies.get('remote_oidc','')),
                            db.flows.c.expires_at > time.time(), conn=c)
            require(row, 400, 'Login flow expired')
            c.execute(delete(db.flows).where(db.flows.c.hash == row['hash']))
        request.scope['session'] = dict(row['data'])
        try:
            result = await oauth.identity.authorize_access_token(request,
                claims_options={'iss': {'essential': True, 'value': config.oidc.issuer}})
            info = result.get('userinfo')
            require(info and info.get('sub') and info.get('iss') == config.oidc.issuer, 400, 'Invalid identity')
        except HTTPException:
            raise
        except Exception:
            # OAuth responses may contain credentials; never log the provider's exception.
            raise HTTPException(400, 'Identity verification failed; start login again') from None
        old = request.cookies.get('remote_session')
        if old:
            with store.transaction() as c:
                c.execute(delete(db.logins).where(db.logins.c.hash == digest(old)))
        raw, _, _ = store.login(config.oidc.issuer, info['sub'], info.get('name') or info.get('preferred_username') or info['sub'])
        response = RedirectResponse('/')
        response.delete_cookie('remote_oidc', path='/auth')
        response.set_cookie('remote_session', raw, httponly=True, secure=not config.development,
                            samesite='lax', max_age=config.session_seconds, path='/')
        return response

    @routes.post('/auth/logout')
    async def logout(request: Request):
        user = mutation(request)
        with request.app.state.store.transaction() as c:
            c.execute(delete(db.logins).where(db.logins.c.hash == user['hash']))
        await request.app.state.connections.logout(user['hash'])
        from starlette.responses import JSONResponse
        response = JSONResponse({'logged_out':True})
        response.delete_cookie('remote_session', path='/')
        return response

    return routes
