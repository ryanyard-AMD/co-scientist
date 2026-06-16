from contextlib import asynccontextmanager

from fastapi import FastAPI

from coscientist.config import settings
from coscientist.database import Base, engine
from coscientist.models import approach, evidence, score  # noqa: F401 — registers ORM models
from coscientist.routers import approach as approach_router
from coscientist.routers import goal as goal_router
from coscientist.routers import ontology as ontology_router
from coscientist.routers import score as score_router
from coscientist.routers import scout as scout_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="Co-Scientist API",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(score_router.router, prefix=settings.api_prefix)
app.include_router(approach_router.router, prefix=settings.api_prefix)
app.include_router(goal_router.router, prefix=settings.api_prefix)
app.include_router(ontology_router.router, prefix=settings.api_prefix)
app.include_router(scout_router.router, prefix=settings.api_prefix)


@app.get(f"{settings.api_prefix}/health")
def health():
    return {"status": "ok"}
