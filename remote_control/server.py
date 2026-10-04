"""Run one relay worker; WebSocket ownership is intentionally process-local."""
import argparse
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse

from .config import ServerConfig, load
from .store import Store
from .connections import Connections


def create_app(config:ServerConfig):
    store=Store(config)
    @asynccontextmanager
    async def lifespan(app):
        yield
    app=FastAPI(lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None)
    from .ingress import IngressLimits
    app.add_middleware(IngressLimits,attachment_limit=config.attachment_limit)
    app.state.config=config; app.state.store=store; app.state.connections=Connections(store)
    from . import auth,api,connections
    app.include_router(auth.router(config)); app.include_router(api.router()); app.include_router(connections.router())

    @app.middleware('http')
    async def security_headers(request:Request,call_next):
        response=await call_next(request)
        response.headers['Cache-Control']='no-store'
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Referrer-Policy']='no-referrer'
        response.headers['X-Frame-Options']='DENY'
        return response

    @app.get('/health')
    async def health():
        return {'ok':True,'auth_configured':config.oidc is not None,'database':'sqlite-development' if store.engine.dialect.name=='sqlite' else 'postgresql',
                'protocol':1,'workers':1}

    if config.static_dir:
        root=Path(config.static_dir).resolve()
        @app.get('/{path:path}')
        async def static(path:str):
            candidate=(root/path).resolve()
            if not candidate.is_relative_to(root) or not candidate.is_file():
                candidate=root/'index.html'
            return FileResponse(candidate)
    return app


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--config',required=True)
    config=load(parser.parse_args().config,ServerConfig)
    import uvicorn
    uvicorn.run(create_app(config),host=config.host,port=config.port,workers=1,access_log=False,
                ws_max_size=2*1024*1024,ws_max_queue=32)


if __name__=='__main__':
    main()
