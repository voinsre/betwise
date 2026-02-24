import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.api import admin, chat, fixtures, predictions, tickets

logger = logging.getLogger(__name__)

# Rate limiter (keyed by remote IP)
limiter = Limiter(key_func=get_remote_address, default_limits=["120/minute"])

_is_production = bool(os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("ENVIRONMENT") == "production")


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(
    title="BetWise API",
    description="AI-powered football betting intelligence",
    version="0.1.0",
    lifespan=lifespan,
    docs_url=None if _is_production else "/docs",
    redoc_url=None if _is_production else "/redoc",
    openapi_url=None if _is_production else "/openapi.json",
)

app.state.limiter = limiter

# CORS — restrict to known origins
_allowed_origins = [
    "https://wizer.bet",
    "https://www.wizer.bet",
    "https://ideal-amazement-production-53df.up.railway.app",
    "http://localhost:3000",
]
_extra = os.getenv("CORS_ORIGINS", "")
if _extra:
    _allowed_origins.extend(o.strip() for o in _extra.split(",") if o.strip())

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type", "Authorization"],
)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    if _is_production:
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    return response


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled error on %s %s: %s", request.method, request.url.path, exc, exc_info=True)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded. Try again later."})


app.include_router(fixtures.router, prefix="/api/fixtures", tags=["fixtures"])
app.include_router(predictions.router, prefix="/api/predictions", tags=["predictions"])
app.include_router(tickets.router, prefix="/api/tickets", tags=["tickets"])
app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
app.include_router(admin.router, prefix="/api/admin", tags=["admin"])


@app.get("/api/health")
async def health_check():
    return {"status": "ok"}
