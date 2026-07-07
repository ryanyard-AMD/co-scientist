from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from coscientist.config import settings
from coscientist.database import Base, engine
from coscientist.models import approval, approach, critic, device, evidence, execution, experiment, feedback, governance, handoff, hypothesis, roadmap, score, synthesis, validation  # noqa: F401 — registers ORM models
from coscientist.routers import approval as approval_router
from coscientist.routers import critic as critic_router
from coscientist.routers import device as device_router
from coscientist.routers import evaluation as evaluation_router
from coscientist.routers import execution as execution_router
from coscientist.routers import feedback as feedback_router
from coscientist.routers import governance as governance_router
from coscientist.routers import approach as approach_router
from coscientist.routers import experiment as experiment_router
from coscientist.routers import goal as goal_router
from coscientist.routers import hypothesis as hypothesis_router
from coscientist.routers import ontology as ontology_router
from coscientist.routers import result_bundle as result_bundle_router
from coscientist.routers import roadmap as roadmap_router
from coscientist.routers import score as score_router
from coscientist.routers import scout as scout_router
from coscientist.routers import validation as validation_router
from coscientist.web import routes as web_routes
from coscientist.web.templates import STATIC_DIR


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="Co-Scientist API",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(governance_router.router, prefix=settings.api_prefix)
app.include_router(governance_router.audit_router, prefix=settings.api_prefix)
app.include_router(governance_router.label_router, prefix=settings.api_prefix)
app.include_router(validation_router.router, prefix=settings.api_prefix)
app.include_router(device_router.router, prefix=settings.api_prefix)
app.include_router(roadmap_router.router, prefix=settings.api_prefix)
app.include_router(score_router.router, prefix=settings.api_prefix)
app.include_router(score_router.updates_router, prefix=settings.api_prefix)
app.include_router(approach_router.router, prefix=settings.api_prefix)
app.include_router(goal_router.router, prefix=settings.api_prefix)
app.include_router(approval_router.router, prefix=settings.api_prefix)
app.include_router(experiment_router.router, prefix=settings.api_prefix)
app.include_router(execution_router.router, prefix=settings.api_prefix)
app.include_router(result_bundle_router.router, prefix=settings.api_prefix)
app.include_router(hypothesis_router.router, prefix=settings.api_prefix)
app.include_router(ontology_router.router, prefix=settings.api_prefix)
app.include_router(scout_router.router, prefix=settings.api_prefix)
app.include_router(critic_router.router, prefix=settings.api_prefix)
app.include_router(evaluation_router.router, prefix=settings.api_prefix)
app.include_router(feedback_router.router, prefix=settings.api_prefix)

app.include_router(web_routes.router)
app.mount("/ui/static", StaticFiles(directory=str(STATIC_DIR)), name="ui-static")


@app.get(f"{settings.api_prefix}/health")
def health():
    return {"status": "ok"}
