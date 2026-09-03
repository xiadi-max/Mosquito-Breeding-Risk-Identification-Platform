from fastapi import APIRouter

from app.api.routes import artifacts, grids, health, images, inference, jobs, m5, mosaic, rois, tasks, version


api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(version.router)
api_router.include_router(tasks.router)
api_router.include_router(images.router)
api_router.include_router(artifacts.router)
api_router.include_router(mosaic.router)
api_router.include_router(jobs.router)
api_router.include_router(rois.router)
api_router.include_router(grids.router)
api_router.include_router(inference.router)
api_router.include_router(m5.router)
