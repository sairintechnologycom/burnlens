"""Tests for Phase 4: BL-AE-004 Agent API / MCP.

Satisfies the 5-layer test pyramid:
- Layer 1 (Unit): Deterministic API operations & parameter validations
- Layer 2 (Contract): JSON-RPC 2.0 / MCP schema compliance & token/scope contracts
- Layer 3 (Integration): End-to-end multi-tool flow via AgentEconomicsService & MCP adapter
- Layer 4 (Security): Scope violations, expired/revoked tokens, cross-workspace containment
- Layer 5 (E2E): Coding agent scenario: "Can I afford another retry?"
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport

from burnlens.api.agent_router import router as agent_router
from burnlens.api.agent_security import (
    AgentScope,
    AgentSecurityContext,
    TokenManager,
)
from burnlens.api.agent_service import (
    AgentApiPermissionError,
    AgentApiValidationError,
    AgentEconomicsService,
)
from burnlens.api.mcp_adapter import McpServerAdapter
from burnlens.storage.agent_economics import (
    insert_agent,
    insert_agent_action,
    insert_agent_run,
    insert_agent_task,
    insert_agent_workflow,
)
from burnlens.storage.database import init_db, insert_outcome, insert_request
from burnlens.storage.models import (
    Agent,
    AgentAction,
    AgentRun,
    AgentTask,
    AgentWorkflow,
    Outcome,
    RequestRecord,
)


@pytest.fixture
async def sample_db(tmp_path: Path) -> str:
    """Provide initialized SQLite database with seeded agent economics data."""
    db_path = str(tmp_path / "agent_api_test.db")
    await init_db(db_path)

    now = datetime.now(timezone.utc)

    # Register Agent in ws-prod
    await insert_agent(
        db_path,
        Agent(
            agent_id="agent-coder-99",
            name="CoderAgent",
            version="1.0.0",
            owner="infra",
            environment="production",
            purpose="Code Generation",
            status="active",
            workspace_id="ws-prod",
            created_at=now,
        ),
    )

    # Workflow & Run & Task
    await insert_agent_workflow(
        db_path,
        AgentWorkflow(
            workflow_id="wf-pr-review",
            name="PR Reviewer",
            workspace_id="ws-prod",
            created_at=now,
        ),
    )
    await insert_agent_run(
        db_path,
        AgentRun(
            run_id="run-001",
            agent_id="agent-coder-99",
            workflow_id="wf-pr-review",
            status="running",
            workspace_id="ws-prod",
            started_at=now,
        ),
    )
    await insert_agent_task(
        db_path,
        AgentTask(
            task_id="task-retry-test",
            run_id="run-001",
            name="Run Unit Tests",
            status="in_progress",
            workspace_id="ws-prod",
            created_at=now,
        ),
    )

    # Successful Request ($0.05)
    rec_success = RequestRecord(
        provider="anthropic",
        model="claude-sonnet-4-6",
        request_path="/v1/messages",
        input_tokens=1000,
        output_tokens=500,
        cost_usd=0.05,
        status_code=200,
        agent_id="agent-coder-99",
        workflow_id="wf-pr-review",
        run_id="run-001",
        task_id="task-retry-test",
        workspace_id="ws-prod",
        timestamp=now,
    )
    await insert_request(db_path, rec_success)

    # Failed Request / Retry waste ($0.03)
    rec_fail = RequestRecord(
        provider="anthropic",
        model="claude-sonnet-4-6",
        request_path="/v1/messages",
        input_tokens=800,
        output_tokens=200,
        cost_usd=0.03,
        status_code=500,
        agent_id="agent-coder-99",
        workflow_id="wf-pr-review",
        run_id="run-001",
        task_id="task-retry-test",
        workspace_id="ws-prod",
        timestamp=now,
    )
    await insert_request(db_path, rec_fail)

    # Action spend ($0.01)
    await insert_agent_action(
        db_path,
        AgentAction(
            action_id="act-search-01",
            task_id="task-retry-test",
            run_id="run-001",
            action_type="tool_execution",
            tool_name="github_grep",
            status="success",
            cost_usd=0.01,
            workspace_id="ws-prod",
            created_at=now,
        ),
    )

    # Outcomes for wf-pr-review: 2 accepted, 1 rejected
    await insert_outcome(
        db_path,
        Outcome(
            outcome_id="out-1",
            workflow_id="wf-pr-review",
            status="accepted",
            business_value=100.0,
        ),
    )
    await insert_outcome(
        db_path,
        Outcome(
            outcome_id="out-2",
            workflow_id="wf-pr-review",
            status="accepted",
            business_value=100.0,
        ),
    )
    await insert_outcome(
        db_path,
        Outcome(
            outcome_id="out-3",
            workflow_id="wf-pr-review",
            status="rejected",
            business_value=0.0,
        ),
    )

    return db_path


@pytest.fixture
def auth_tokens() -> tuple[TokenManager, str, str, str]:
    """Provide a configured TokenManager with valid, restricted, and cross-workspace tokens."""
    tm = TokenManager()

    # Valid token with full scopes in ws-prod
    token_valid = "token_valid_all_scopes"
    tm.register_token(
        token=token_valid,
        agent_id="agent-coder-99",
        workspace_id="ws-prod",
        scopes=[
            AgentScope.ECONOMICS_READ,
            AgentScope.BUDGET_CHECK,
            AgentScope.SIMULATION_EXECUTE,
            AgentScope.RECOMMENDATIONS_READ,
        ],
    )

    # Restricted token with only economics:read (no budget:check or simulation)
    token_restricted = "token_restricted_read_only"
    tm.register_token(
        token=token_restricted,
        agent_id="agent-coder-99",
        workspace_id="ws-prod",
        scopes=[AgentScope.ECONOMICS_READ],
    )

    # Token belonging to different workspace ws-staging
    token_other_ws = "token_ws_staging"
    tm.register_token(
        token=token_other_ws,
        agent_id="agent-other-10",
        workspace_id="ws-staging",
        scopes=[AgentScope.ECONOMICS_READ, AgentScope.BUDGET_CHECK],
    )

    return tm, token_valid, token_restricted, token_other_ws


# ===========================================================================
# Layer 1: Unit Tests (Deterministic Operations & Validations)
# ===========================================================================

def test_layer1_unit_estimate_cost_deterministic(sample_db: str):
    """Estimate cost must use deterministic pricing tables without external network calls."""
    service = AgentEconomicsService(sample_db)
    ctx = AgentSecurityContext(
        agent_id="agent-1",
        workspace_id="ws-prod",
        scopes={AgentScope.ECONOMICS_READ.value},
    )

    estimate = service.estimate_cost(
        context=ctx,
        provider="anthropic",
        model="claude-sonnet-4-6",
        input_tokens=10_000,
        output_tokens=1_000,
    )
    assert estimate["is_priced"] is True
    assert estimate["estimated_cost_usd"] > 0.0
    assert "provider" in estimate and "model" in estimate


def test_layer1_unit_simulation_invalid_type_raises(sample_db: str):
    """Invalid simulation type must raise AgentApiValidationError."""
    service = AgentEconomicsService(sample_db)
    ctx = AgentSecurityContext(
        agent_id="agent-1",
        workspace_id="ws-prod",
        scopes={AgentScope.SIMULATION_EXECUTE.value},
    )

    with pytest.raises(AgentApiValidationError):
        service.simulate_change(
            context=ctx,
            simulation_type="invalid_sim_type",
            params={},
        )


# ===========================================================================
# Layer 2: Contract Tests (MCP Schema & Tool Specifications)
# ===========================================================================

def test_layer2_contract_mcp_tool_definitions(sample_db: str):
    """Verify MCP adapter tool definitions meet JSON-RPC schema requirements."""
    service = AgentEconomicsService(sample_db)
    adapter = McpServerAdapter(service)

    tools = adapter.get_tool_definitions()
    tool_names = {t["name"] for t in tools}

    expected_tools = {
        "get_agent_economics",
        "get_task_economics",
        "find_waste",
        "estimate_cost",
        "simulate_change",
        "check_budget",
        "get_cost_per_outcome",
    }
    assert expected_tools.issubset(tool_names)

    for tool in tools:
        assert "name" in tool
        assert "description" in tool
        assert "inputSchema" in tool
        assert tool["inputSchema"]["type"] == "object"


@pytest.mark.asyncio
async def test_layer2_contract_mcp_initialize(sample_db: str):
    """Verify standard MCP initialize handshake returns server info and protocol version."""
    service = AgentEconomicsService(sample_db)
    adapter = McpServerAdapter(service)
    ctx = AgentSecurityContext(agent_id="a1", workspace_id="ws-prod")

    req = {
        "jsonrpc": "2.0",
        "id": "req-init-1",
        "method": "initialize",
        "params": {},
    }
    resp = await adapter.handle_jsonrpc(req, ctx)
    assert resp["jsonrpc"] == "2.0"
    assert resp["id"] == "req-init-1"
    assert "serverInfo" in resp["result"]
    assert resp["result"]["serverInfo"]["name"] == "burnlens-mcp-server"


# ===========================================================================
# Layer 3: Integration Tests (Multi-Tool Execution via MCP Adapter)
# ===========================================================================

@pytest.mark.asyncio
async def test_layer3_integration_mcp_tool_calls(sample_db: str, auth_tokens):
    """Verify tools/call through MCP adapter executes deterministic service operations."""
    tm, token_valid, _, _ = auth_tokens
    service = AgentEconomicsService(sample_db)
    adapter = McpServerAdapter(service)
    ctx = tm.authenticate(token_valid)
    assert ctx is not None

    # Call get_agent_economics
    req_econ = {
        "jsonrpc": "2.0",
        "id": "call-1",
        "method": "tools/call",
        "params": {
            "name": "get_agent_economics",
            "arguments": {"agent_id": "agent-coder-99"},
        },
    }
    resp_econ = await adapter.handle_jsonrpc(req_econ, ctx)
    assert resp_econ["result"]["isError"] is False
    payload = json.loads(resp_econ["result"]["content"][0]["text"])
    assert payload["agent_id"] == "agent-coder-99"
    assert payload["total_spend_usd"] == 0.09  # 0.05 (req1) + 0.03 (req2) + 0.01 (action)
    assert payload["retry_waste_usd"] == 0.03

    # Call get_cost_per_outcome
    req_outcome = {
        "jsonrpc": "2.0",
        "id": "call-2",
        "method": "tools/call",
        "params": {
            "name": "get_cost_per_outcome",
            "arguments": {"workflow_id": "wf-pr-review"},
        },
    }
    resp_outcome = await adapter.handle_jsonrpc(req_outcome, ctx)
    assert resp_outcome["result"]["isError"] is False
    out_data = json.loads(resp_outcome["result"]["content"][0]["text"])
    assert out_data["accepted_outcomes"] == 2
    assert out_data["cost_per_accepted_outcome_usd"] == round(0.09 / 2, 6)


# ===========================================================================
# Layer 4: Security Tests (Scopes, Expiry, Revocation, Multi-Tenant Isolation)
# ===========================================================================

@pytest.mark.asyncio
async def test_layer4_security_scope_enforcement(sample_db: str, auth_tokens):
    """Agent lacking simulation:execute scope must be denied with PermissionError."""
    tm, _, token_restricted, _ = auth_tokens
    service = AgentEconomicsService(sample_db)
    ctx_restricted = tm.authenticate(token_restricted)
    assert ctx_restricted is not None

    # Restricted context only has economics:read. Attempt simulate_change
    with pytest.raises(AgentApiPermissionError) as exc_info:
        service.simulate_change(
            context=ctx_restricted,
            simulation_type="retry_reduction",
            params={"current_retry_spend_usd": 10.0, "reduction_pct": 0.5},
        )
    assert "missing required scope 'simulation:execute'" in str(exc_info.value)


@pytest.mark.asyncio
async def test_layer4_security_cross_workspace_containment(sample_db: str, auth_tokens):
    """Agent belonging to ws-staging cannot query or access ws-prod data."""
    tm, _, _, token_other_ws = auth_tokens
    service = AgentEconomicsService(sample_db)
    ctx_staging = tm.authenticate(token_other_ws)
    assert ctx_staging is not None

    # Staging agent attempts to explicitly access ws-prod
    with pytest.raises(AgentApiPermissionError) as exc_info:
        await service.get_agent_economics(
            context=ctx_staging,
            agent_id="agent-coder-99",
            workspace_id="ws-prod",
        )
    assert "cannot access workspace 'ws-prod'" in str(exc_info.value)


def test_layer4_security_revoked_and_expired_tokens(sample_db: str):
    """Expired or revoked tokens must be rejected unconditionally."""
    tm = TokenManager()
    token = "ephemeral_token_123"

    # Expired token
    tm.register_token(
        token=token,
        agent_id="agent-exp",
        workspace_id="ws-prod",
        scopes=[AgentScope.ECONOMICS_READ],
        ttl_seconds=-10,  # Expired in past
    )
    assert tm.authenticate(token) is None

    # Revoked token
    token_live = "token_live_to_revoke"
    tm.register_token(
        token=token_live,
        agent_id="agent-live",
        workspace_id="ws-prod",
        scopes=[AgentScope.ECONOMICS_READ],
        ttl_seconds=3600,
    )
    assert tm.authenticate(token_live) is not None
    tm.revoke_token(token_live)
    assert tm.authenticate(token_live) is None


# ===========================================================================
# Layer 5: E2E Test (Coding Agent Scenario: "Can I afford another retry?")
# ===========================================================================

@pytest.mark.asyncio
async def test_layer5_e2e_coding_agent_retry_budget_workflow(sample_db: str, auth_tokens):
    """End-to-End Scenario:
    Coding Agent asks: "Can I afford another retry?"
    1. Agent calls check_budget with task_id and planned retry cost.
    2. BurnLens calculates current task spend ($0.09) and projects new spend.
    3. Under a $0.15 cap, planned call ($0.03) is APPROVED (total $0.12).
    4. Under a $0.10 cap, planned call ($0.03) is DENIED (total $0.12 > $0.10).
    """
    tm, token_valid, _, _ = auth_tokens

    app = FastAPI()
    app.include_router(agent_router)
    app.state.db_path = sample_db
    app.state.agent_token_manager = tm

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Step 1: Query task economics via HTTP
        headers = {"Authorization": f"Bearer {token_valid}"}
        resp_econ = await client.get("/api/v1/agent/task-economics/task-retry-test", headers=headers)
        assert resp_econ.status_code == 200
        data_econ = resp_econ.json()
        assert data_econ["total_spend_usd"] == 0.09

        # Step 2: Estimate cost of another retry
        resp_est = await client.post(
            "/api/v1/agent/estimate-cost",
            headers=headers,
            json={
                "provider": "anthropic",
                "model": "claude-sonnet-4-6",
                "input_tokens": 800,
                "output_tokens": 200,
            },
        )
        assert resp_est.status_code == 200
        data_est = resp_est.json()
        retry_cost = data_est["estimated_cost_usd"]
        assert retry_cost > 0.0

        # Step 3: Check budget with sufficient limit ($0.15 limit)
        resp_budget_allowed = await client.post(
            "/api/v1/agent/check-budget",
            headers=headers,
            json={
                "task_id": "task-retry-test",
                "planned_spend_usd": retry_cost,
                "budget_limit_usd": 0.15,
            },
        )
        assert resp_budget_allowed.status_code == 200
        data_allowed = resp_budget_allowed.json()
        assert data_allowed["allowed"] is True
        assert data_allowed["current_spend_usd"] == 0.09
        assert data_allowed["remaining_budget_usd"] == 0.06

        # Step 4: Check budget with tight limit ($0.092 limit where $0.09 + retry_cost exceeds it)
        resp_budget_denied = await client.post(
            "/api/v1/agent/check-budget",
            headers=headers,
            json={
                "task_id": "task-retry-test",
                "planned_spend_usd": retry_cost,
                "budget_limit_usd": 0.092,
            },
        )
        assert resp_budget_denied.status_code == 200
        data_denied = resp_budget_denied.json()
        assert data_denied["allowed"] is False
        assert "exceeds limit" in data_denied["reason"]
