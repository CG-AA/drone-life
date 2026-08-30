"""FastAPI assembly: one port serves REST + WebSocket + the built frontend."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from .api import admin_listener, routes_admin, routes_public
from .api import ws as ws_module
from .api.auth import AdminPortGate, RateLimiter, StrikeGuard
from .api.ws import Hub
from .config import Settings, check_secrets
from .service import DroneLifeService

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    service = DroneLifeService(settings)
    hub = Hub(service)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # guard here, not at import: main.py's module-level create_app() runs under
        # pytest with the placeholder defaults, and refusing there would kill the suite
        refusal = check_secrets(settings)
        if refusal:
            log.error(refusal)
            raise RuntimeError(refusal)
        if settings.allow_default_secrets:
            log.warning("ALLOW_DEFAULT_SECRETS=1 — placeholder secrets permitted, dev only")
        await service.start()
        hub.start()
        try:
            # the console's own loopback listener; 404 on the public port (AdminPortGate)
            admin = await admin_listener.start(app, settings)
        except Exception:
            await hub.stop()
            await service.stop()
            raise
        try:
            yield
        finally:
            await admin_listener.stop(admin)
            await hub.stop()
            await service.stop()

    app = FastAPI(title="drone-life", lifespan=lifespan)
    app.state.settings = settings
    app.state.service = service
    app.state.hub = hub
    app.state.join_limiter = RateLimiter(settings.join_rate_limit_per_minute)
    app.state.join_strikes = StrikeGuard(settings.join_strikes, settings.join_lockout_s)
    app.state.submit_limiter = RateLimiter(settings.submit_rate_limit_per_minute)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request, exc: StarletteHTTPException):
        detail = exc.detail if isinstance(exc.detail, dict) else {"code": "error",
                                                                  "msg": str(exc.detail)}
        return JSONResponse({"error": detail}, status_code=exc.status_code)

    app.include_router(routes_public.router)
    app.include_router(routes_admin.router)
    app.include_router(ws_module.router)
    # outermost, so a console path on the public listener never reaches a route
    app.add_middleware(AdminPortGate, admin_port=settings.admin_port)

    @app.get("/healthz")
    async def healthz() -> dict:
        return service.health()

    dist = settings.abs_static_dir
    if dist.is_dir():
        @app.get("/submit", include_in_schema=False)
        async def submit_page() -> FileResponse:
            return FileResponse(dist / "submit.html")

        @app.get("/admin", include_in_schema=False)
        async def admin_page() -> FileResponse:
            return FileResponse(dist / "admin.html")

        app.mount("/", StaticFiles(directory=dist, html=True), name="static")

    return app


app = create_app()
