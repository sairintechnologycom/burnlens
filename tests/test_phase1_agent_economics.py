"""Phase 1: Agent Economics Foundation Certification Suite (BL-AE-001).

Validates domain entities, correlation dimensions, recursive parent-child rollups,
workspace isolation, and the golden coding agent journey without altering canonical ledger truth.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite
import pytest

from burnlens.storage.agent_economics import (
    get_agent,
    get_agent_economics,
    get_run_economics,
    get_task_economics,
    get_workflow_economics,
    get_workspace_agent_attribution,
    insert_agent,
    insert_agent_action,
    insert_agent_run,
    insert_agent_task,
    insert_agent_workflow,
    list_agents,
)
from burnlens.storage.database import (
    init_db,
    insert_outcome,
    insert_request,
)
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
async def test_db(tmp_path):
    db_path = str(tmp_path / "phase1_agent_economics.db")
    await init_db(db_path)
    return db_path


# ===========================================================================
# Layer 1 — Unit: Domain Entity Instantiation & Defaults
# ===========================================================================

def test_layer1_unit_domain_entities():
    """Verify Agent, Workflow, Run, Task, and Action dataclass definitions and defaults."""
    agent = Agent(
        agent_id="agent-coder-01",
        name="Coding Agent",
        owner="sec-team",
        purpose="Automated CVE patch generation",
    )
    assert agent.agent_id == "agent-coder-01"
    assert agent.status == "active"
    assert agent.version == "1.0.0"

    workflow = AgentWorkflow(workflow_id="wf-patching", name="Security Patching")
    assert workflow.workflow_id == "wf-patching"

    run = AgentRun(
        run_id="run-001",
        agent_id="agent-coder-01",
        workflow_id="wf-patching",
    )
    assert run.parent_run_id is None
    assert run.status == "active"

    task = AgentTask(task_id="task-001", run_id="run-001", name="Review AST")
    assert task.status == "active"

    action = AgentAction(
        action_id="act-001",
        task_id="task-001",
        run_id="run-001",
        tool_name="git_create_pr",
        cost_usd=0.15,
    )
    assert action.action_type == "tool_call"
    assert action.cost_usd == 0.15


# ===========================================================================
# Layer 2 — Contract: Schema Integrity & Backward Compatibility
# ===========================================================================

@pytest.mark.asyncio
async def test_layer2_contract_agent_tables_and_columns(test_db):
    """Verify that all 5 agent tables and 6 nullable correlation columns exist."""
    async with aiosqlite.connect(test_db) as db:
        # Check tables
        cursor = await db.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = {row[0] for row in await cursor.fetchall()}
        required_tables = {
            "agents",
            "agent_workflows",
            "agent_runs",
            "agent_tasks",
            "agent_actions",
        }
        for t in required_tables:
            assert t in tables, f"Missing table {t}"

        # Check nullable correlation columns on requests
        cursor = await db.execute("PRAGMA table_info(requests);")
        columns = {row[1] for row in await cursor.fetchall()}
        required_columns = {
            "agent_id",
            "workflow_id",
            "run_id",
            "task_id",
            "action_id",
            "parent_run_id",
        }
        for c in required_columns:
            assert c in columns, f"Missing column {c} on requests table"


@pytest.mark.asyncio
async def test_layer2_contract_backward_compatibility(test_db):
    """Ensure old events without agent context (agent_id = NULL) insert cleanly and calculate accurately."""
    now = datetime.now(timezone.utc)
    rec = RequestRecord(
        provider="openai",
        model="gpt-4o",
        request_path="/v1/chat/completions",
        timestamp=now,
        input_tokens=1000,
        output_tokens=500,
        cost_usd=0.0075,
        tags={"team": "core"},
        workspace_id="ws_legacy",
    )
    row_id = await insert_request(test_db, rec)
    assert row_id > 0

    async with aiosqlite.connect(test_db) as db:
        cursor = await db.execute(
            "SELECT cost_usd, agent_id, workflow_id FROM requests WHERE id = ?", (row_id,)
        )
        row = await cursor.fetchone()
        assert row[0] == 0.0075
        assert row[1] is None
        assert row[2] is None


# ===========================================================================
# Layer 3 — Integration: Recursive Parent-Child Rollup & Attribution Invariant
# ===========================================================================

@pytest.mark.asyncio
async def test_layer3_integration_parent_child_recursive_rollup(test_db):
    """Verify Parent-Child recursive hierarchy economics with NO double counting.

    Parent Agent Total = $10:
      - Direct Parent: $0
      - Child A: $3
      - Child B: $7
      -> Rollup = $10
    """
    now = datetime.now(timezone.utc)
    # 1. Register agents
    await insert_agent(test_db, Agent(agent_id="planner", name="Planner Agent"))
    await insert_agent(test_db, Agent(agent_id="researcher", name="Research Agent"))
    await insert_agent(test_db, Agent(agent_id="coder", name="Coding Agent"))

    # 2. Register runs
    await insert_agent_run(
        test_db,
        AgentRun(run_id="run-parent", agent_id="planner", parent_run_id=None),
    )
    await insert_agent_run(
        test_db,
        AgentRun(run_id="run-child-a", agent_id="researcher", parent_run_id="run-parent"),
    )
    await insert_agent_run(
        test_db,
        AgentRun(run_id="run-child-b", agent_id="coder", parent_run_id="run-parent"),
    )

    # 3. Add requests to Child A ($3) and Child B ($7)
    rec_child_a = RequestRecord(
        provider="openai",
        model="gpt-4o",
        request_path="/v1/chat/completions",
        timestamp=now,
        cost_usd=3.00,
        tags={"agent_id": "researcher", "run_id": "run-child-a"},
        run_id="run-child-a",
        agent_id="researcher",
    )
    rec_child_b = RequestRecord(
        provider="anthropic",
        model="claude-3-5-sonnet-20241022",
        request_path="/v1/messages",
        timestamp=now,
        cost_usd=7.00,
        tags={"agent_id": "coder", "run_id": "run-child-b"},
        run_id="run-child-b",
        agent_id="coder",
    )
    await insert_request(test_db, rec_child_a)
    await insert_request(test_db, rec_child_b)

    # 4. Query recursive economics on parent run
    parent_econ = await get_run_economics(test_db, "run-parent")
    assert parent_econ["run_id"] == "run-parent"
    assert parent_econ["direct_spend_usd"] == 0.0
    assert parent_econ["children_spend_usd"] == 10.0
    assert parent_econ["total_rollup_spend_usd"] == 10.0
    assert parent_econ["child_runs_count"] == 2
    assert parent_econ["children_breakdown"]["run-child-a"]["total_spend_usd"] == 3.0
    assert parent_econ["children_breakdown"]["run-child-b"]["total_spend_usd"] == 7.0


@pytest.mark.asyncio
async def test_layer3_integration_attribution_invariant(test_db):
    """Verify: total_workspace_spend = agent_attributed_spend + unattributed_spend."""
    now = datetime.now(timezone.utc)
    # Agent request: $4.50
    rec_agent = RequestRecord(
        provider="openai",
        model="gpt-4o",
        request_path="/v1/chat/completions",
        timestamp=now,
        cost_usd=4.50,
        agent_id="agent-analyst",
        tags={"agent_id": "agent-analyst"},
        workspace_id="ws_default",
    )
    # Unattributed request: $1.50
    rec_unattributed = RequestRecord(
        provider="openai",
        model="gpt-4o",
        request_path="/v1/chat/completions",
        timestamp=now,
        cost_usd=1.50,
        tags={"feature": "search"},
        workspace_id="ws_default",
    )
    await insert_request(test_db, rec_agent)
    await insert_request(test_db, rec_unattributed)

    attribution = await get_workspace_agent_attribution(test_db, "ws_default")
    assert attribution["total_workspace_spend_usd"] == 6.00
    assert attribution["agent_attributed_spend_usd"] == 4.50
    assert attribution["unattributed_spend_usd"] == 1.50
    assert attribution["invariant_holds"] is True


# ===========================================================================
# Layer 4 — Security: Tenant Isolation
# ===========================================================================

@pytest.mark.asyncio
async def test_layer4_security_tenant_isolation(test_db):
    """Ensure Workspace A cannot access or see agent entities/runs from Workspace B."""
    # Register agents in separate workspaces
    await insert_agent(test_db, Agent(agent_id="agent-corp-a", name="Corp A Agent", workspace_id="ws_corp_a"))
    await insert_agent(test_db, Agent(agent_id="agent-corp-b", name="Corp B Agent", workspace_id="ws_corp_b"))

    corp_a_agents = await list_agents(test_db, workspace_id="ws_corp_a")
    corp_b_agents = await list_agents(test_db, workspace_id="ws_corp_b")

    assert len(corp_a_agents) == 1
    assert corp_a_agents[0].agent_id == "agent-corp-a"

    assert len(corp_b_agents) == 1
    assert corp_b_agents[0].agent_id == "agent-corp-b"

    # Cross-workspace fetch returns None
    assert await get_agent(test_db, "agent-corp-a", workspace_id="ws_corp_b") is None


# ===========================================================================
# Layer 5 — End-to-End: Golden Coding Agent Journey
# ===========================================================================

@pytest.mark.asyncio
async def test_layer5_e2e_golden_coding_agent_journey(test_db):
    """Canonical Golden Scenario:
    Coding agent (Codex security-fixer v2.3) fixes a vulnerable dependency:
      - Starts task: 'Fix vulnerable dependency'
      - Calls LLM: $2.73 model spend
      - Retries once: $0.34 retry waste
      - GitHub tool actions: $0.71 CI/tool cost
      - PR opened and merged: Outcome ACCEPTED
      - Asserts:
          Total cost = $3.78
          Model cost = $2.73
          Tool/Action cost = $0.71
          Retry waste = $0.34
          Outcome = ACCEPTED
          Cost per accepted outcome = $3.78
    """
    now = datetime.now(timezone.utc)
    agent_id = "codex-security-fixer-v2.3"
    workflow_id = "cve-dependency-fix"
    run_id = "run-cve-892"
    task_id = "task-patch-libxml"

    # 1. Register agent, workflow, run, task
    await insert_agent(
        test_db,
        Agent(
            agent_id=agent_id,
            name="Codex Security Fixer",
            version="2.3",
            purpose="Vulnerability remediation",
            workspace_id="ws_prod",
        ),
    )
    await insert_agent_workflow(
        test_db,
        AgentWorkflow(
            workflow_id=workflow_id,
            name="Remediate CVE",
            workspace_id="ws_prod",
        ),
    )
    await insert_agent_run(
        test_db,
        AgentRun(
            run_id=run_id,
            agent_id=agent_id,
            workflow_id=workflow_id,
            workspace_id="ws_prod",
        ),
    )
    await insert_agent_task(
        test_db,
        AgentTask(
            task_id=task_id,
            run_id=run_id,
            name="Fix vulnerable dependency",
            workspace_id="ws_prod",
        ),
    )

    # 2. Model call 1: successful LLM analysis ($2.73)
    rec_llm = RequestRecord(
        provider="anthropic",
        model="claude-3-5-sonnet-20241022",
        request_path="/v1/messages",
        timestamp=now,
        input_tokens=3000,
        output_tokens=600,
        cost_usd=2.73,
        status_code=200,
        agent_id=agent_id,
        workflow_id=workflow_id,
        run_id=run_id,
        task_id=task_id,
        workspace_id="ws_prod",
    )
    await insert_request(test_db, rec_llm)

    # 3. Model call 2: failed attempt / retry ($0.34)
    rec_retry = RequestRecord(
        provider="anthropic",
        model="claude-3-5-sonnet-20241022",
        request_path="/v1/messages",
        timestamp=now,
        input_tokens=400,
        output_tokens=50,
        cost_usd=0.34,
        status_code=500,  # retry trigger
        agent_id=agent_id,
        workflow_id=workflow_id,
        run_id=run_id,
        task_id=task_id,
        workspace_id="ws_prod",
    )
    await insert_request(test_db, rec_retry)

    # 4. Tool calls: GitHub branch, commit, PR actions ($0.71)
    action_gh = AgentAction(
        action_id="act-gh-pr-12",
        task_id=task_id,
        run_id=run_id,
        action_type="github_tool",
        tool_name="create_pull_request",
        cost_usd=0.71,
        workspace_id="ws_prod",
    )
    await insert_agent_action(test_db, action_gh)

    # 5. Outcome accepted (PR merged)
    outcome = Outcome(
        outcome_id="pr-4029-merged",
        workflow_id=workflow_id,
        status="accepted",
        business_value=420.0,  # Projected monthly saving
        source="github",
        metadata={"pr_number": 4029, "repo": "backend-service"},
    )
    await insert_outcome(test_db, outcome)

    # 6. Verify Task Economics
    task_econ = await get_task_economics(test_db, task_id, workspace_id="ws_prod")
    assert round(task_econ["total_spend_usd"], 2) == 3.78
    assert round(task_econ["model_spend_usd"], 2) == 3.07  # $2.73 + $0.34
    assert round(task_econ["tool_action_spend_usd"], 2) == 0.71
    assert round(task_econ["retry_waste_usd"], 2) == 0.34

    # 7. Verify Workflow Economics & Cost per Accepted Outcome
    wf_econ = await get_workflow_economics(test_db, workflow_id, workspace_id="ws_prod")
    assert round(wf_econ["total_spend_usd"], 2) == 3.78
    assert wf_econ["accepted_outcomes"] == 1
    assert round(wf_econ["cost_per_accepted_outcome_usd"], 2) == 3.78
