"""FastAPI REST routes for external agent control plane consumption (BL-AE-004).

Exposes:
- GET  /api/v1/agent/economics/{agent_id}
- GET  /api/v1/agent/task-economics/{task_id}
- GET  /api/v1/agent/waste
- POST /api/v1/agent/estimate-cost
- POST /api/v1/agent/simulate-change
- POST /api/v1/agent/check-budget
- GET  /api/v1/agent/cost-per-outcome/{workflow_id}
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from burnlens.api.agent_security import AgentSecurityContext, TokenManager
from burnlens.api.agent_service import (
    AgentApiPermissionError,
    AgentApiValidationError,
    AgentEconomicsService,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/agent", tags=["agent-control-plane"])

# Global token manager registry for FastAPI app state
_DEFAULT_TOKEN_MANAGER = TokenManager()


def get_token_manager(request: Request) -> TokenManager:
    """Extract TokenManager from request.app.state or use default."""
    return getattr(request.app.state, "agent_token_manager", _DEFAULT_TOKEN_MANAGER)


def get_agent_service(request: Request) -> AgentEconomicsService:
    """Extract AgentEconomicsService configured with current db_path."""
    db_path = getattr(request.app.state, "db_path", "burnlens.db")
    return AgentEconomicsService(db_path=db_path)


async def get_current_agent_context(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    token_manager: TokenManager = Depends(get_token_manager),
) -> AgentSecurityContext:
    """Authenticate incoming Agent Bearer token."""
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
        )
    parts = authorization.split(" ")
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization header format. Expected 'Bearer <token>'",
        )
    token = parts[1]
    ctx = token_manager.authenticate(token)
    if not ctx:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid, expired, or revoked token",
        )
    return ctx


# ---------------------------------------------------------------------------
# Request Schemas
# ---------------------------------------------------------------------------

class CostEstimateRequest(BaseModel):
    provider: str = Field(..., description="LLM provider name, e.g. anthropic, openai")
    model: str = Field(..., description="Model identifier")
    input_tokens: int = Field(..., ge=0, description="Estimated input prompt tokens")
    output_tokens: int = Field(default=1000, ge=0, description="Max or expected completion tokens")
    cache_read_tokens: int = Field(default=0, ge=0, description="Expected cached tokens")


class SimulationRequest(BaseModel):
    simulation_type: str = Field(..., description="'model_switch', 'retry_reduction', or 'prompt_caching'")
    params: dict[str, Any] = Field(..., description="Simulation parameters")


class BudgetCheckRequest(BaseModel):
    task_id: Optional[str] = Field(default=None, description="Task ID to check")
    agent_id: Optional[str] = Field(default=None, description="Agent ID to check")
    workspace_id: Optional[str] = Field(default=None, description="Target workspace ID")
    planned_spend_usd: float = Field(default=0.0, ge=0.0, description="Cost of upcoming call/retry")
    budget_limit_usd: Optional[float] = Field(default=None, gt=0.0, description="Budget cap override")


# ---------------------------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------------------------

@router.get("/economics/{agent_id}")
async def get_agent_economics_endpoint(
    agent_id: str,
    workspace_id: Optional[str] = Query(default=None),
    since: Optional[str] = Query(default=None),
    context: AgentSecurityContext = Depends(get_current_agent_context),
    service: AgentEconomicsService = Depends(get_agent_service),
) -> dict[str, Any]:
    try:
        return await service.get_agent_economics(
            context, agent_id=agent_id, workspace_id=workspace_id, since=since
        )
    except AgentApiPermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))


@router.get("/task-economics/{task_id}")
async def get_task_economics_endpoint(
    task_id: str,
    workspace_id: Optional[str] = Query(default=None),
    context: AgentSecurityContext = Depends(get_current_agent_context),
    service: AgentEconomicsService = Depends(get_agent_service),
) -> dict[str, Any]:
    try:
        return await service.get_task_economics(
            context, task_id=task_id, workspace_id=workspace_id
        )
    except AgentApiPermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))


@router.get("/waste")
async def find_waste_endpoint(
    agent_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
    context: AgentSecurityContext = Depends(get_current_agent_context),
    service: AgentEconomicsService = Depends(get_agent_service),
) -> dict[str, Any]:
    try:
        return await service.find_waste(
            context, agent_id=agent_id, workspace_id=workspace_id
        )
    except AgentApiPermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))


@router.post("/estimate-cost")
async def estimate_cost_endpoint(
    body: CostEstimateRequest,
    context: AgentSecurityContext = Depends(get_current_agent_context),
    service: AgentEconomicsService = Depends(get_agent_service),
) -> dict[str, Any]:
    try:
        return service.estimate_cost(
            context,
            provider=body.provider,
            model=body.model,
            input_tokens=body.input_tokens,
            output_tokens=body.output_tokens,
            cache_read_tokens=body.cache_read_tokens,
        )
    except AgentApiPermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))


@router.post("/simulate-change")
async def simulate_change_endpoint(
    body: SimulationRequest,
    context: AgentSecurityContext = Depends(get_current_agent_context),
    service: AgentEconomicsService = Depends(get_agent_service),
) -> dict[str, Any]:
    try:
        return service.simulate_change(
            context,
            simulation_type=body.simulation_type,
            params=body.params,
        )
    except AgentApiPermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except AgentApiValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))


@router.post("/check-budget")
async def check_budget_endpoint(
    body: BudgetCheckRequest,
    context: AgentSecurityContext = Depends(get_current_agent_context),
    service: AgentEconomicsService = Depends(get_agent_service),
) -> dict[str, Any]:
    try:
        return await service.check_budget(
            context,
            task_id=body.task_id,
            agent_id=body.agent_id,
            workspace_id=body.workspace_id,
            planned_spend_usd=body.planned_spend_usd,
            budget_limit_usd=body.budget_limit_usd,
        )
    except AgentApiPermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))


@router.get("/cost-per-outcome/{workflow_id}")
async def get_cost_per_outcome_endpoint(
    workflow_id: str,
    workspace_id: Optional[str] = Query(default=None),
    context: AgentSecurityContext = Depends(get_current_agent_context),
    service: AgentEconomicsService = Depends(get_agent_service),
) -> dict[str, Any]:
    try:
        return await service.get_cost_per_outcome(
            context, workflow_id=workflow_id, workspace_id=workspace_id
        )
    except AgentApiPermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
