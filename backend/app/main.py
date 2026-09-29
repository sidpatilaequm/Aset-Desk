from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from starlette.middleware.sessions import SessionMiddleware
from .auth import router as auth_router
from .config import settings
from .routers import admin, assets, returns, sales, tickets

app = FastAPI(title="Asset Desk", docs_url="/api/docs" if settings.dev_login else None, redoc_url=None)

UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


@app.middleware("http")
async def csrf_and_headers(request: Request, call_next):
    # State-changing API calls must come from our own page (custom header can't be sent cross-site without CORS).
    if request.method in UNSAFE and (request.url.path.startswith("/api/") or request.url.path == "/auth/logout"):
        if request.headers.get("x-requested-with") != "AssetDesk":
            return JSONResponse({"detail": "Missing request header."}, status_code=403)
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    return resp


app.add_middleware(SessionMiddleware, secret_key=settings.secret_key, session_cookie="assetdesk_session",
                   max_age=12 * 3600, same_site="lax", https_only=settings.cookie_secure)

app.include_router(auth_router)
app.include_router(admin.router)
app.include_router(assets.router)
app.include_router(tickets.router)
app.include_router(returns.router)
app.include_router(sales.router)


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(settings.frontend_dir / "index.html", headers={"Cache-Control": "no-store"})


@app.get("/healthz", include_in_schema=False)
def health():
    return {"ok": True}
