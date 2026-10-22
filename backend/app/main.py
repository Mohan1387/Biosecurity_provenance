# FastAPI application entry point
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import init_db
from app.routers import admin, auth, chat, profiler, clusterer, detector
from app.routers import provenance
from app.services.provenance import IntegrityError
from app.database import async_session
from app.models import AuditLog
from fastapi.responses import JSONResponse
import json
import logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(
    title=settings.PROJECT_NAME,
    lifespan=lifespan,
)

# CORS — allow Streamlit frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(auth.router, prefix=settings.API_V1_PREFIX)
app.include_router(admin.router, prefix=settings.API_V1_PREFIX)
app.include_router(chat.router, prefix=settings.API_V1_PREFIX)
app.include_router(profiler.router, prefix=settings.API_V1_PREFIX)
app.include_router(detector.router, prefix=settings.API_V1_PREFIX)
app.include_router(clusterer.router, prefix=settings.API_V1_PREFIX)
app.include_router(provenance.router, prefix=settings.API_V1_PREFIX)


@app.exception_handler(IntegrityError)
async def integrity_failure(request, exc):
    logging.getLogger("provenance").error("Integrity failure %s %s", exc.reason, exc.subject)
    async with async_session() as db:
        db.add(AuditLog(action="integrity_failure", detail=json.dumps({
            "reason": exc.reason, "subject": exc.subject, "path": request.url.path})))
        await db.commit()
    return JSONResponse(status_code=409, content={"detail": "Provenance verification failed",
        "reason": exc.reason, "subject": exc.subject})


@app.get("/health")
async def health():
    return {"status": "ok"}
