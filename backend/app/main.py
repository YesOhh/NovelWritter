from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.foreshadows import router as foreshadows_router
from app.api.generate import router as generate_router
from app.api.health import router as health_router
from app.api.ocr import router as ocr_router
from app.api.projects import router as projects_router
from app.api.reference import router as reference_router
from app.api.settings import router as settings_router
from app.api.truth_files import router as truth_files_router
from app.config import settings
from app.db import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="AI Agent 小说写作系统", version="0.2.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(generate_router)
app.include_router(projects_router)
app.include_router(settings_router)
app.include_router(foreshadows_router)
app.include_router(reference_router)
app.include_router(truth_files_router)
app.include_router(health_router)
app.include_router(ocr_router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
