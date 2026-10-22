# Tier-gated tool registry for the Claude agent
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Callable

from app.models import Tier

TIER_ORDER = {Tier.open: 0, Tier.controlled: 1, Tier.restricted: 2}


class ToolDefinition:
    """A single tool that the agent can invoke."""

    def __init__(
        self,
        name: str,
        description: str,
        input_schema: dict,
        handler: Callable[..., Any],
        min_tier: Tier,
    ):
        self.name = name
        self.description = description
        self.input_schema = input_schema
        self.handler = handler
        self.min_tier = min_tier

    def to_anthropic(self) -> dict:
        """Return the Anthropic tool-use schema dict."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


class ToolRegistry:
    """Central registry of tier-gated tools."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(
        self,
        name: str,
        description: str,
        input_schema: dict,
        handler: Callable[..., Any],
        min_tier: Tier,
    ) -> None:
        self._tools[name] = ToolDefinition(
            name=name,
            description=description,
            input_schema=input_schema,
            handler=handler,
            min_tier=min_tier,
        )

    def tools_for_tier(self, tier: Tier) -> list[ToolDefinition]:
        """Return tools accessible at the given tier."""
        user_level = TIER_ORDER[tier]
        return [
            t for t in self._tools.values() if TIER_ORDER[t.min_tier] <= user_level
        ]

    def get(self, name: str) -> ToolDefinition | None:
        return self._tools.get(name)


# ── Singleton registry ────────────────────────────────
registry = ToolRegistry()


# ── Tool handlers ─────────────────────────────────────
# Each handler receives the tool input dict and returns a string result.


def _search_public_docs(query: str) -> str:
    """Search publicly available documentation (mock)."""
    mock_docs = {
        "tcp": "TCP (Tiered Compute Platform) is a prototype platform providing tiered access to AI agents. Users are assigned Open, Controlled, or Restricted tiers.",
        "tiers": "Open tier: basic Q&A and public doc search. Controlled tier: adds sensitive dataset queries and analysis tools. Restricted tier: full admin access including user management and usage stats.",
        "agent": "The AI agent is powered by Claude and can use tier-gated tools to assist users with research, analysis, and platform administration.",
        "security": "TCP uses JWT-based authentication, bcrypt password hashing, and role-based access control with three access tiers.",
    }
    results = []
    query_lower = query.lower()
    for key, doc in mock_docs.items():
        if key in query_lower or any(w in doc.lower() for w in query_lower.split()):
            results.append(doc)
    if not results:
        return "No matching documents found."
    return "\n\n".join(results)


def _get_current_time() -> str:
    """Return the current UTC timestamp."""
    return datetime.now(timezone.utc).isoformat()


def _query_dataset(dataset: str, query: str) -> str:
    """Query a mock sensitive dataset (controlled tier)."""
    mock_datasets = {
        "employee_metrics": [
            {"name": "Alice", "department": "Engineering", "performance": 4.2, "projects": 7},
            {"name": "Bob", "department": "Research", "performance": 3.8, "projects": 5},
            {"name": "Carol", "department": "Engineering", "performance": 4.5, "projects": 9},
            {"name": "Dave", "department": "Research", "performance": 4.0, "projects": 6},
        ],
        "project_budgets": [
            {"project": "Alpha", "budget": 150000, "spent": 120000, "status": "on-track"},
            {"project": "Beta", "budget": 200000, "spent": 195000, "status": "at-risk"},
            {"project": "Gamma", "budget": 80000, "spent": 45000, "status": "under-budget"},
        ],
        "incident_reports": [
            {"id": "IR-001", "severity": "high", "status": "resolved", "summary": "Unauthorized access attempt blocked"},
            {"id": "IR-002", "severity": "medium", "status": "open", "summary": "Unusual data export pattern detected"},
            {"id": "IR-003", "severity": "low", "status": "resolved", "summary": "Failed login attempts from single IP"},
        ],
    }
    data = mock_datasets.get(dataset)
    if data is None:
        available = ", ".join(mock_datasets.keys())
        return f"Dataset '{dataset}' not found. Available datasets: {available}"
    return json.dumps(data, indent=2)


def _analyze_data(data_json: str, analysis_type: str) -> str:
    """Run a simple analysis on provided JSON data (mock)."""
    try:
        data = json.loads(data_json)
    except json.JSONDecodeError:
        return "Error: Invalid JSON data provided."

    if not isinstance(data, list):
        return "Error: Expected a JSON array."

    if analysis_type == "count":
        return f"Record count: {len(data)}"
    if analysis_type == "summary":
        return f"Dataset has {len(data)} records with fields: {', '.join(data[0].keys()) if data else 'none'}"
    if analysis_type == "aggregate":
        numeric_fields = [k for k, v in (data[0] if data else {}).items() if isinstance(v, (int, float))]
        if not numeric_fields:
            return "No numeric fields found for aggregation."
        aggs = {}
        for field in numeric_fields:
            values = [r[field] for r in data if isinstance(r.get(field), (int, float))]
            aggs[field] = {"min": min(values), "max": max(values), "avg": round(sum(values) / len(values), 2)}
        return json.dumps(aggs, indent=2)
    return f"Unknown analysis type: {analysis_type}. Supported: count, summary, aggregate."


def _list_platform_users() -> str:
    """List platform users (restricted tier, mock for tool context)."""
    return "Use the /admin/users API endpoint for live user data. This tool confirms you have restricted-tier access to user management."


def _get_usage_stats() -> str:
    """Get platform usage statistics (restricted tier, mock)."""
    stats = {
        "total_users": 12,
        "active_sessions": 4,
        "total_messages_today": 87,
        "total_tokens_today": {"input": 45200, "output": 23100},
        "estimated_cost_today": 0.42,
        "top_users_by_messages": [
            {"username": "researcher1", "messages": 32},
            {"username": "analyst2", "messages": 25},
            {"username": "admin", "messages": 18},
        ],
    }
    return json.dumps(stats, indent=2)


# ── Register all tools ────────────────────────────────

registry.register(
    name="search_public_docs",
    description="Search publicly available TCP platform documentation. Use this to answer questions about the platform, its tiers, security, and capabilities.",
    input_schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query to look up in the documentation.",
            },
        },
        "required": ["query"],
    },
    handler=lambda inp: _search_public_docs(inp["query"]),
    min_tier=Tier.open,
)

registry.register(
    name="get_current_time",
    description="Get the current UTC date and time.",
    input_schema={
        "type": "object",
        "properties": {},
    },
    handler=lambda inp: _get_current_time(),
    min_tier=Tier.open,
)

registry.register(
    name="query_dataset",
    description="Query a sensitive dataset. Available datasets: employee_metrics, project_budgets, incident_reports. Returns dataset records as JSON.",
    input_schema={
        "type": "object",
        "properties": {
            "dataset": {
                "type": "string",
                "description": "Name of the dataset to query (employee_metrics, project_budgets, or incident_reports).",
            },
            "query": {
                "type": "string",
                "description": "Description of what you want to find or filter.",
            },
        },
        "required": ["dataset", "query"],
    },
    handler=lambda inp: _query_dataset(inp["dataset"], inp["query"]),
    min_tier=Tier.controlled,
)

registry.register(
    name="analyze_data",
    description="Analyze JSON data with basic aggregations. Supports analysis types: count (record count), summary (field listing), aggregate (min/max/avg of numeric fields).",
    input_schema={
        "type": "object",
        "properties": {
            "data_json": {
                "type": "string",
                "description": "JSON string containing an array of records to analyze.",
            },
            "analysis_type": {
                "type": "string",
                "enum": ["count", "summary", "aggregate"],
                "description": "Type of analysis to perform.",
            },
        },
        "required": ["data_json", "analysis_type"],
    },
    handler=lambda inp: _analyze_data(inp["data_json"], inp["analysis_type"]),
    min_tier=Tier.controlled,
)

registry.register(
    name="list_platform_users",
    description="List all users registered on the TCP platform. Restricted-tier access only.",
    input_schema={
        "type": "object",
        "properties": {},
    },
    handler=lambda inp: _list_platform_users(),
    min_tier=Tier.restricted,
)

registry.register(
    name="get_usage_stats",
    description="Get platform usage statistics including active sessions, token counts, costs, and top users. Restricted-tier access only.",
    input_schema={
        "type": "object",
        "properties": {},
    },
    handler=lambda inp: _get_usage_stats(),
    min_tier=Tier.restricted,
)
