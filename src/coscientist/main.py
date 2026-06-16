from contextlib import asynccontextmanager

from fastapi import FastAPI

from coscientist.config import settings
from coscientist.database import Base, engine
from coscientist.routers import goal as goal_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="Co-Scientist API",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(goal_router.router, prefix=settings.api_prefix)


@app.get(f"{settings.api_prefix}/health")
def health():
    return {"status": "ok"}
