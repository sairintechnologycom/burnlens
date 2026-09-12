"""Model Context Protocol (MCP) Server Adapter for BurnLens (BL-AE-004).

Exposes BurnLens deterministic economics, budgets, simulations, and unit metrics
as standard MCP tools (tools/list, tools/call) adhering to the JSON-RPC 2.0 / MCP specification.

Tools exposed:
- get_agent_economics
- get_task_economics
- find_waste
- estimate_cost
- simulate_change
- check_budget
- get_cost_per_outcome
"""
from __future__ import annotations

import json
import logging
from typing import Any, Callable, Coroutine

from burnlens.api.agent_security import AgentScope, AgentSecurityContext
from burnlens.api.agent_service import (
    AgentApiPermissionError,
    AgentApiValidationError,
    AgentEconomicsService,
)

logger = logging.getLogger(__name__)

# Protocol version
MCP_PROTOCOL_VERSION = "2024-11-05"


class McpServerAdapter:
    """Standard MCP adapter exposing BurnLens deterministic capabilities."""

    def __init__(self, service: AgentEconomicsService) -> None:
        self.service = service
        self._tools = self._build_tool_registry()

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        """Return MCP tool schemas adhering to tools/list specification."""
        return [
            {
                "name": "get_agent_economics",
                "description": "Retrieve exact, deterministic spend, requests, tool calls, and waste for an agent.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "agent_id": {
                            "type": "string",
                            "description": "The unique identifier of the agent.",
                        },
                        "since": {
                            "type": "string",
                            "description": "Optional ISO timestamp (e.g. 2026-09-01T00:00:00Z) to filter from.",
                        },
                    },
                    "required": ["agent_id"],
                },
            },
            {
                "name": "get_task_economics",
                "description": "Retrieve granular cost breakdown, LLM spend, and tool action costs for a specific task.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "task_id": {
                            "type": "string",
                            "description": "The unique identifier of the task.",
                        },
                    },
                    "required": ["task_id"],
                },
            },
            {
                "name": "find_waste",
                "description": "Quantify retry waste, failed requests, and uncacheable spend for an agent or workspace.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "agent_id": {
                            "type": "string",
                            "description": "Optional agent ID. If omitted, analyzes the caller's workspace.",
                        },
                    },
                },
            },
            {
                "name": "estimate_cost",
                "description": "Compute the exact USD cost of an upcoming LLM completion before invoking it.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "provider": {
                            "type": "string",
                            "description": "Provider name (e.g. anthropic, openai).",
                        },
                        "model": {
                            "type": "string",
                            "description": "Model ID (e.g. claude-sonnet-4-6, gpt-4o).",
                        },
                        "input_tokens": {
                            "type": "integer",
                            "description": "Estimated prompt token count.",
                        },
                        "output_tokens": {
                            "type": "integer",
                            "default": 1000,
                            "description": "Expected completion token count.",
                        },
                        "cache_read_tokens": {
                            "type": "integer",
                            "default": 0,
                            "description": "Expected cached token count.",
                        },
                    },
                    "required": ["provider", "model", "input_tokens"],
                },
            },
            {
                "name": "simulate_change",
                "description": "Simulate counterfactual cost impact of model switches, prompt caching, or retry reduction.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "simulation_type": {
                            "type": "string",
                            "enum": ["model_switch", "retry_reduction", "prompt_caching"],
                            "description": "Type of simulation to perform.",
                        },
                        "params": {
                            "type": "object",
                            "description": "Simulation parameters (e.g. current_model, target_model, input_tokens).",
                        },
                    },
                    "required": ["simulation_type", "params"],
                },
            },
            {
                "name": "check_budget",
                "description": "Check whether an agent or task has remaining budget for another retry or step.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "task_id": {
                            "type": "string",
                            "description": "Optional task ID to evaluate.",
                        },
                        "agent_id": {
                            "type": "string",
                            "description": "Optional agent ID to evaluate.",
                        },
                        "planned_spend_usd": {
                            "type": "number",
                            "default": 0.0,
                            "description": "Cost of the proposed upcoming action.",
                        },
                        "budget_limit_usd": {
                            "type": "number",
                            "description": "Optional budget limit override.",
                        },
                    },
                },
            },
            {
                "name": "get_cost_per_outcome",
                "description": "Calculate unit economics: total spend divided by accepted outcomes for a workflow.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "workflow_id": {
                            "type": "string",
                            "description": "The unique identifier of the workflow.",
                        },
                    },
                    "required": ["workflow_id"],
                },
            },
        ]

    def _build_tool_registry(self) -> dict[str, Any]:
        return {
            "get_agent_economics": self._handle_get_agent_economics,
            "get_task_economics": self._handle_get_task_economics,
            "find_waste": self._handle_find_waste,
            "estimate_cost": self._handle_estimate_cost,
            "simulate_change": self._handle_simulate_change,
            "check_budget": self._handle_check_budget,
            "get_cost_per_outcome": self._handle_get_cost_per_outcome,
        }

    async def handle_jsonrpc(
        self, request: dict[str, Any], context: AgentSecurityContext
    ) -> dict[str, Any]:
        """Handle incoming JSON-RPC 2.0 MCP request."""
        req_id = request.get("id")
        method = request.get("method")

        if request.get("jsonrpc") != "2.0":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32600, "message": "Invalid Request: expected jsonrpc 2.0"},
            }

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {"tools": {}},
                    "serverInfo": {
                        "name": "burnlens-mcp-server",
                        "version": "1.0.0",
                    },
                },
            }

        elif method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"tools": self.get_tool_definitions()},
            }

        elif method == "tools/call":
            params = request.get("params", {})
            tool_name = params.get("name")
            arguments = params.get("arguments", {})

            handler = self._tools.get(tool_name)
            if not handler:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32601, "message": f"Method not found: tool '{tool_name}'"},
                }

            try:
                content = await handler(arguments, context)
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(content, indent=2),
                            }
                        ],
                        "isError": False,
                    },
                }
            except AgentApiPermissionError as exc:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": f"Permission Denied: {exc}"}],
                        "isError": True,
                    },
                }
            except AgentApiValidationError as exc:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": f"Validation Error: {exc}"}],
                        "isError": True,
                    },
                }
            except Exception as exc:
                logger.exception("Internal error in MCP tool call '%s'", tool_name)
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": f"Internal Error: {exc}"}],
                        "isError": True,
                    },
                }

        else:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Unsupported method: '{method}'"},
            }

    # Tool Handlers
    async def _handle_get_agent_economics(
        self, args: dict[str, Any], context: AgentSecurityContext
    ) -> dict[str, Any]:
        return await self.service.get_agent_economics(
            context=context,
            agent_id=args["agent_id"],
            since=args.get("since"),
        )

    async def _handle_get_task_economics(
        self, args: dict[str, Any], context: AgentSecurityContext
    ) -> dict[str, Any]:
        return await self.service.get_task_economics(
            context=context,
            task_id=args["task_id"],
        )

    async def _handle_find_waste(
        self, args: dict[str, Any], context: AgentSecurityContext
    ) -> dict[str, Any]:
        return await self.service.find_waste(
            context=context,
            agent_id=args.get("agent_id"),
        )

    async def _handle_estimate_cost(
        self, args: dict[str, Any], context: AgentSecurityContext
    ) -> dict[str, Any]:
        return self.service.estimate_cost(
            context=context,
            provider=args["provider"],
            model=args["model"],
            input_tokens=int(args["input_tokens"]),
            output_tokens=int(args.get("output_tokens", 1000)),
            cache_read_tokens=int(args.get("cache_read_tokens", 0)),
        )

    async def _handle_simulate_change(
        self, args: dict[str, Any], context: AgentSecurityContext
    ) -> dict[str, Any]:
        return self.service.simulate_change(
            context=context,
            simulation_type=args["simulation_type"],
            params=args["params"],
        )

    async def _handle_check_budget(
        self, args: dict[str, Any], context: AgentSecurityContext
    ) -> dict[str, Any]:
        return await self.service.check_budget(
            context=context,
            task_id=args.get("task_id"),
            agent_id=args.get("agent_id"),
            planned_spend_usd=float(args.get("planned_spend_usd", 0.0)),
            budget_limit_usd=float(args["budget_limit_usd"]) if args.get("budget_limit_usd") is not None else None,
        )

    async def _handle_get_cost_per_outcome(
        self, args: dict[str, Any], context: AgentSecurityContext
    ) -> dict[str, Any]:
        return await self.service.get_cost_per_outcome(
            context=context,
            workflow_id=args["workflow_id"],
        )
