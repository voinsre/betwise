from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import admin, chat, fixtures, predictions, tickets


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(
    title="BetWise API",
    description="AI-powered football betting intelligence",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(fixtures.router, prefix="/api/fixtures", tags=["fixtures"])
app.include_router(predictions.router, prefix="/api/predictions", tags=["predictions"])
app.include_router(tickets.router, prefix="/api/tickets", tags=["tickets"])
app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
app.include_router(admin.router, prefix="/api/admin", tags=["admin"])


@app.get("/api/health")
async def health_check():
    return {"status": "ok"}
