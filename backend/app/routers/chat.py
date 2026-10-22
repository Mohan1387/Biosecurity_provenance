# Chat router — Claude agent endpoints
import json

import anthropic
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.config import settings
from app.database import get_db
from app.models import ConversationMessage, LLMUsage, User
from app.schemas import ChatMessageRead, ChatRequest, ChatResponse, ToolCallInfo
from app.services.agent import AgentService
from app.services.agents.logger import record_data_access, record_query

router = APIRouter(prefix="/chat", tags=["chat"])

_agent = AgentService()


@router.post("", response_model=ChatResponse)
async def send_message(
    body: ChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not settings.ANTHROPIC_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ANTHROPIC_API_KEY is not configured",
        )

    # Load conversation history from DB
    result = await db.execute(
        select(ConversationMessage)
        .where(ConversationMessage.user_id == current_user.id)
        .order_by(ConversationMessage.timestamp)
    )
    history_rows = result.scalars().all()

    # Build messages list for Claude
    messages: list[dict] = []
    for row in history_rows:
        messages.append({"role": row.role, "content": row.content})
    messages.append({"role": "user", "content": body.message})

    # Call agent — surface Anthropic API errors as clean JSON (e.g. low credit
    # balance, invalid key, rate limits) instead of an unhandled 500/plain-text body.
    try:
        agent_result = await _agent.chat(messages, current_user.tier)
    except anthropic.APIStatusError as exc:
        message = exc.message
        try:
            message = exc.response.json().get("error", {}).get("message", message)
        except Exception:
            pass
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Anthropic API error: {message}",
        )
    except anthropic.APIError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Anthropic API error: {exc}",
        )

    # Persist user message
    db.add(ConversationMessage(
        user_id=current_user.id,
        role="user",
        content=body.message,
    ))

    # Persist assistant response
    tool_calls_json = (
        json.dumps(agent_result["tool_calls"])
        if agent_result["tool_calls"]
        else None
    )
    db.add(ConversationMessage(
        user_id=current_user.id,
        role="assistant",
        content=agent_result["assistant_text"],
        tool_calls_json=tool_calls_json,
    ))

    # Track LLM usage
    usage = agent_result["usage"]
    db.add(LLMUsage(
        user_id=current_user.id,
        model=settings.ANTHROPIC_MODEL,
        input_tokens=usage.get("input_tokens", 0),
        output_tokens=usage.get("output_tokens", 0),
    ))

    # Logger: record query for Detector analysis
    await record_query(
        db,
        user_id=current_user.id,
        query_text=body.message,
        tools_invoked=agent_result["tool_calls"] or None,
        response_summary=agent_result["assistant_text"][:500] if agent_result["assistant_text"] else None,
    )

    # Logger: record dataset accesses from tool calls
    for tc in agent_result["tool_calls"]:
        if tc.get("name") == "query_dataset":
            dataset = tc.get("input", {}).get("dataset", "unknown")
            from app.models import Tier as TierEnum
            await record_data_access(
                db,
                user_id=current_user.id,
                dataset_name=dataset,
                dataset_tier=TierEnum.controlled,
                access_type="query",
            )

    await db.commit()

    return ChatResponse(
        reply=agent_result["assistant_text"],
        tool_calls=[ToolCallInfo(**tc) for tc in agent_result["tool_calls"]],
        usage=usage,
    )


@router.get("/history", response_model=list[ChatMessageRead])
async def get_history(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(ConversationMessage)
        .where(ConversationMessage.user_id == current_user.id)
        .order_by(ConversationMessage.timestamp)
    )
    return result.scalars().all()


@router.post("/reset", status_code=status.HTTP_204_NO_CONTENT)
async def reset_conversation(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await db.execute(
        delete(ConversationMessage)
        .where(ConversationMessage.user_id == current_user.id)
    )
    await db.commit()
