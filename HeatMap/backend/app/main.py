from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.config import settings
from app.db import init_db_pool, close_db_pool, ensure_schema, DB_PATH
from app.routers import density, drone, alerts
from app.routers.auth import router as auth_router, reconcile_drone_statuses
import os

app = FastAPI(
    title="Drone Surveillance API",
    description="Backend API for drone-based crowd density monitoring",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(density.router)
app.include_router(drone.router)
app.include_router(alerts.router)
app.include_router(auth_router)


os.makedirs(settings.MEDIA_VIDEOS_DIR, exist_ok=True)
app.mount("/videos", StaticFiles(directory=settings.MEDIA_VIDEOS_DIR), name="videos")


@app.on_event("startup")
async def on_startup():
    try:
        init_db_pool()
        ensure_schema()
        reconcile_drone_statuses()
    except Exception as exc:
        # Keep API available even when DB is temporarily unavailable.
        print(f"Warning: could not initialize database pool: {exc}")


@app.on_event("shutdown")
async def on_shutdown():
    close_db_pool()

@app.get("/")
async def root():
    return {"status": "online", "service": "Drone Surveillance API"}


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "db_backend": "sqlite",
        "db_path": DB_PATH,
    }
