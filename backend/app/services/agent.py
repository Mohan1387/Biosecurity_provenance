# Claude agent service — wraps the Anthropic Messages API with tier-gated tools
from __future__ import annotations

import logging
from typing import Any

import anthropic

from app.config import settings
from app.models import Tier
from app.services.tools import registry

logger = logging.getLogger(__name__)

SYSTEM_PROMPTS = {
    Tier.open: (
        "You are TCP Assistant, a helpful AI agent on the Tiered Compute Platform. "
        "The user has **Open** tier access. You can search public documentation and "
        "answer general questions. You do NOT have access to sensitive datasets or "
        "admin functions. If the user asks for something beyond your access, politely "
        "explain they need a higher tier."
    ),
    Tier.controlled: (
        "You are TCP Assistant, a helpful AI agent on the Tiered Compute Platform. "
        "The user has **Controlled** tier access. You can search public docs, query "
        "sensitive datasets (employee_metrics, project_budgets, incident_reports), and "
        "run data analysis. You do NOT have admin-level access. If the user asks for "
        "admin functions, explain they need Restricted tier."
    ),
    Tier.restricted: (
        "You are TCP Assistant, a helpful AI agent on the Tiered Compute Platform. "
        "The user has **Restricted** (admin) tier access. You have full access to all "
        "tools: public docs, sensitive datasets, data analysis, user management, and "
        "usage statistics. Help the user with whatever they need."
    ),
}


class AgentService:
    """Manages a conversation with Claude, enforcing tier-based tool access."""

    def __init__(self) -> None:
        self._client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tier: Tier,
    ) -> dict:
        """Send messages to Claude with tier-appropriate tools.

        Returns a dict with keys:
            assistant_text: str — the final assistant response
            tool_calls: list[dict] — any tool calls made (name, input, result)
            usage: dict — {input_tokens, output_tokens}
        """
        available_tools = registry.tools_for_tier(tier)
        tool_schemas = [t.to_anthropic() for t in available_tools]
        system_prompt = SYSTEM_PROMPTS[tier]

        all_tool_calls: list[dict] = []
        conversation = list(messages)
        total_input_tokens = 0
        total_output_tokens = 0

        # Agentic loop — keep going while Claude wants to use tools
        while True:
            create_kwargs: dict[str, Any] = {
                "model": settings.ANTHROPIC_MODEL,
                "max_tokens": 4096,
                "system": system_prompt,
                "messages": conversation,
            }
            if tool_schemas:
                create_kwargs["tools"] = tool_schemas

            response = self._client.messages.create(**create_kwargs)

            total_input_tokens += response.usage.input_tokens
            total_output_tokens += response.usage.output_tokens

            # If the model didn't request any tool use, we're done
            if response.stop_reason != "tool_use":
                # Extract text from content blocks
                text_parts = [
                    block.text
                    for block in response.content
                    if block.type == "text"
                ]
                return {
                    "assistant_text": "\n".join(text_parts),
                    "tool_calls": all_tool_calls,
                    "usage": {
                        "input_tokens": total_input_tokens,
                        "output_tokens": total_output_tokens,
                    },
                }

            # Process tool calls
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    tool_def = registry.get(block.name)
                    if tool_def is None:
                        result_str = f"Error: Unknown tool '{block.name}'"
                    else:
                        try:
                            result_str = tool_def.handler(block.input)
                        except Exception as exc:
                            logger.exception("Tool %s failed", block.name)
                            result_str = f"Error executing tool: {exc}"

                    all_tool_calls.append({
                        "name": block.name,
                        "input": block.input,
                        "result": result_str,
                    })
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result_str,
                    })

            # Append assistant message + tool results back into conversation
            conversation.append({"role": "assistant", "content": response.content})
            conversation.append({"role": "user", "content": tool_results})
