from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import VERSION
from app.schemas.request import PlanRequest
from app.schemas.response import PlanResponse, HealthResponse
from app.llm.planner import generate_plan

app = FastAPI(
    title="NL-FreeCAD-Agent",
    version=VERSION,
    description="Natural language driven FreeCAD feature tree modeling agent",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse(status="ok", version=VERSION)


@app.post("/agent/plan", response_model=PlanResponse)
async def plan(request: PlanRequest):
    result = generate_plan(request.user_input, request.document_state)
    return PlanResponse(**result)
