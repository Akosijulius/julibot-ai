"""
Conversation endpoints for managing chat conversations.

Supports both authenticated users and guests. Guest conversations are handled
in-memory by the frontend (localStorage) and don't persist in the database.
"""

import asyncio
import json
from datetime import datetime
from typing import AsyncIterator, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.core.exceptions import AIException
from app.core.logging import get_logger
from app.db.database import async_session_maker, get_db
from app.models.conversation import Conversation
from app.models.user import User
from app.schemas.conversation import (
    ChatRequest,
    ChatResponse,
    ConversationCreate,
    ConversationImport,
    ConversationListResponse,
    ConversationResponse,
    ConversationUpdate,
    MessageResponse,
)
from app.services.ai_orchestrator import ChatContext, get_orchestrator
from app.services.chat_service import ChatService

router = APIRouter(prefix="/conversations", tags=["conversations"])
logger = get_logger(__name__)
settings = get_settings()


def _is_guest(user: User) -> bool:
    """Check if the user is a guest (not authenticated)."""
    return getattr(user, "user_type", "registered") == "guest"


def _guest_denied():
    """Raise a 401 for guests trying to use DB-persisted features."""
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Please log in to save and manage conversations",
    )


@router.post("/", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    conv_data: ConversationCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConversationResponse:
    """Create a new conversation. Guest users get a 401."""
    if _is_guest(current_user):
        raise _guest_denied()
    chat_service = ChatService(db)
    conversation = await chat_service.create_conversation(current_user, conv_data)
    return ConversationResponse.model_validate(conversation)


@router.get("/", response_model=List[ConversationListResponse])
async def list_conversations(
    skip: int = 0,
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[ConversationListResponse]:
    """List conversations. Returns empty list for guests."""
    if _is_guest(current_user):
        return []
    chat_service = ChatService(db)
    conversations = await chat_service.get_user_conversations(current_user, skip, limit)
    return [ConversationListResponse.model_validate(c) for c in conversations]


@router.get("/{conversation_id}", response_model=ConversationResponse)
async def get_conversation(
    conversation_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    message_limit: int = Query(100, ge=1, le=500),
) -> ConversationResponse:
    """Get a conversation with messages. Guests can't fetch server-side conversations."""
    if _is_guest(current_user):
        raise _guest_denied()
    chat_service = ChatService(db)
    conversation = await chat_service.get_conversation(conversation_id, current_user)

    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )

    return ConversationResponse.model_validate(conversation)


@router.patch("/{conversation_id}", response_model=ConversationResponse)
async def update_conversation(
    conversation_id: int,
    conv_data: ConversationUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConversationResponse:
    """Update a conversation's title."""
    if _is_guest(current_user):
        raise _guest_denied()
    chat_service = ChatService(db)
    conversation = await chat_service.get_conversation(conversation_id, current_user)

    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )

    updated_conv = await chat_service.update_conversation(conversation, conv_data)
    return ConversationResponse.model_validate(updated_conv)


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a conversation."""
    if _is_guest(current_user):
        raise _guest_denied()
    chat_service = ChatService(db)
    conversation = await chat_service.get_conversation(conversation_id, current_user)

    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )

    await chat_service.delete_conversation(conversation)


@router.post("/import", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
async def import_conversation(
    import_data: ConversationImport,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConversationResponse:
    """
    Import a conversation with its full message history verbatim.

    Used to move a guest's local conversations into their account when they
    sign up or log in — no AI calls are made during import.
    """
    if _is_guest(current_user):
        raise _guest_denied()

    chat_service = ChatService(db)
    conversation = await chat_service.create_conversation(
        current_user,
        ConversationCreate(title=import_data.title),
    )

    for msg in import_data.messages:
        await chat_service.add_message(
            conversation, role=msg.role, content=msg.content
        )

    # Reload the messages collection (identity map may hold a stale empty list)
    await db.refresh(conversation, attribute_names=["messages"])
    return ConversationResponse.model_validate(conversation)


async def _generate_title_background(
    conversation_id: int,
    user_id: int,
    first_message: str,
):
    """Background task to generate and update conversation title."""
    async with async_session_maker() as db:
        try:
            orchestrator = get_orchestrator()
            title = await orchestrator.generate_title(first_message)

            # Update conversation in DB
            chat_service = ChatService(db)
            from app.schemas.conversation import ConversationUpdate
            conversation = await chat_service.get_conversation(conversation_id, user_id)
            if conversation:
                await chat_service.update_conversation(
                    conversation,
                    ConversationUpdate(title=title),
                )
                logger.info(f"Updated conversation {conversation_id} title: {title}")
        except Exception as e:
            logger.warning(f"Background title generation failed: {e}")
        finally:
            await db.close()


@router.post("/chat", response_model=ChatResponse)
async def send_chat_message(
    chat_request: ChatRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChatResponse:
    """
    Send a message and get an AI response (non-streaming).

    - Registered users: conversations are persisted in the database.
    - Guests: a response is returned but the frontend stores messages in
      localStorage only (conversation_id is echoed back unchanged).
    """
    orchestrator = get_orchestrator()

    # ── Guest mode ─────────────────────────────────────────────────────────
    if _is_guest(current_user):
        conv_id = chat_request.conversation_id or 0

        try:
            context = ChatContext(
                user_message=chat_request.message,
                conversation_id=conv_id,
                conversation_history=[],
                stream=False,
            )
            result = await orchestrator.chat(context)
            ai_response_text = result.content
        except AIException as e:
            # Return user-friendly error, not saved to conversation
            ai_response_text = f"[Error] {e.message}"

        return ChatResponse(
            message=MessageResponse(
                id=0,
                conversation_id=conv_id,
                role="assistant",
                content=ai_response_text,
                created_at=datetime.utcnow(),
            ),
            conversation_id=conv_id,
        )

    # ── Registered user: full persistence ───────────────────────────────────
    chat_service = ChatService(db)

    # Get or create conversation
    conversation: Optional[Conversation] = None
    is_new_conversation = False

    if chat_request.conversation_id:
        conversation = await chat_service.get_conversation(
            chat_request.conversation_id, current_user
        )
        if not conversation:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found",
            )
    else:
        # Create new conversation with temporary title
        temp_title = chat_request.message[:30] + ("..." if len(chat_request.message) > 30 else "")
        conversation = await chat_service.create_conversation(
            current_user,
            ConversationCreate(title=temp_title),
        )
        is_new_conversation = True

    # Add user message
    await chat_service.add_message(
        conversation, role="user", content=chat_request.message
    )

    # Reload conversation with messages
    await db.refresh(conversation)
    conversation = await chat_service.get_conversation(conversation.id, current_user)

    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to load conversation",
        )

    # Build context for AI (excluding the user message we just added - orchestrator adds it)
    history = conversation.messages[:-1] if conversation.messages else []

    try:
        # Build chat context
        # mode is normalized inside AIOrchestrator.determine_mode();
        # pass it through even when None — the orchestrator will classify.
        chat_context = ChatContext(
            user_message=chat_request.message,
            conversation_id=conversation.id,
            conversation_history=history,
            mode=chat_request.mode,
            stream=False,
        )

        # Get AI response
        result = await orchestrator.chat(chat_context)
        ai_response_text = result.content

    except AIException as e:
        # Log error but provide user-friendly message
        logger.error(f"AI error in chat: {e.code} - {e.message}")
        ai_response_text = f"[Error] {e.message}"

    # Add AI response message
    ai_message = await chat_service.add_message(
        conversation, role="assistant", content=ai_response_text
    )

    # Generate title in background for new conversations
    if is_new_conversation and not ai_response_text.startswith("[Error]"):
        background_tasks.add_task(
            _generate_title_background,
            conversation.id,
            current_user.id,
            chat_request.message,
        )

    return ChatResponse(
        message=MessageResponse.model_validate(ai_message),
        conversation_id=conversation.id,
    )


@router.post("/chat/stream")
async def send_chat_message_stream(
    chat_request: ChatRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Send a message and get a streaming AI response via Server-Sent Events.

    Returns SSE events with the following format:
    - data: {"type": "content", "content": "..."} - Response chunks
    - data: {"type": "done", "message": {...}} - Final message saved
    - data: {"type": "error", "error": "..."} - Error occurred
    """
    orchestrator = get_orchestrator()

    async def generate_sse() -> AsyncIterator[str]:
        """Generate SSE events from streaming response."""
        nonlocal db, current_user, chat_request

        # For guests
        if _is_guest(current_user):
            conv_id = chat_request.conversation_id or 0
            full_content = []

            try:
                context = ChatContext(
                    user_message=chat_request.message,
                    conversation_id=conv_id,
                    conversation_history=[],
                    stream=True,
                )

                async for chunk in orchestrator.chat_stream(context):
                    if chunk.content:
                        full_content.append(chunk.content)
                        yield f"data: {json.dumps({'type': 'content', 'content': chunk.content})}\n\n"

                    if chunk.is_final:
                        # Send final message event
                        message_data = {
                            "type": "done",
                            "message": {
                                "id": 0,
                                "conversation_id": conv_id,
                                "role": "assistant",
                                "content": "".join(full_content),
                                "created_at": datetime.utcnow().isoformat(),
                            },
                            "conversation_id": conv_id,
                        }
                        yield f"data: {json.dumps(message_data)}\n\n"

            except AIException as e:
                yield f"data: {json.dumps({'type': 'error', 'error': e.message, 'code': e.code})}\n\n"
            except Exception as e:
                logger.exception("Unexpected streaming error for guest")
                yield f"data: {json.dumps({'type': 'error', 'error': 'An unexpected error occurred'})}\n\n"
            return

        # For authenticated users
        chat_service = ChatService(db)

        # Get or create conversation
        conversation: Optional[Conversation] = None
        is_new_conversation = False

        if chat_request.conversation_id:
            conversation = await chat_service.get_conversation(
                chat_request.conversation_id, current_user
            )
            if not conversation:
                error_data = json.dumps({"type": "error", "error": "Conversation not found"})
                yield f"data: {error_data}\n\n"
                return
        else:
            temp_title = chat_request.message[:30] + ("..." if len(chat_request.message) > 30 else "")
            conversation = await chat_service.create_conversation(
                current_user,
                ConversationCreate(title=temp_title),
            )
            is_new_conversation = True

        # Add user message
        await chat_service.add_message(
            conversation, role="user", content=chat_request.message
        )

        # Reload conversation
        await db.refresh(conversation)
        conversation = await chat_service.get_conversation(conversation.id, current_user)

        if not conversation:
            error_data = json.dumps({"type": "error", "error": "Failed to load conversation"})
            yield f"data: {error_data}\n\n"
            return

        # Build history (excluding the user message we just added)
        history = conversation.messages[:-1] if conversation.messages else []

        full_content = []

        try:
            context = ChatContext(
                user_message=chat_request.message,
                conversation_id=conversation.id,
                conversation_history=history,
                stream=True,
            )

            async for chunk in orchestrator.chat_stream(context):
                if chunk.content:
                    full_content.append(chunk.content)
                    yield f"data: {json.dumps({'type': 'content', 'content': chunk.content})}\n\n"

                if chunk.is_final:
                    # Save the complete message
                    ai_content = "".join(full_content)
                    ai_message = await chat_service.add_message(
                        conversation, role="assistant", content=ai_content
                    )

                    # Send final message event
                    message_data = {
                        "type": "done",
                        "message": {
                            "id": ai_message.id,
                            "conversation_id": ai_message.conversation_id,
                            "role": ai_message.role,
                            "content": ai_content,
                            "created_at": ai_message.created_at.isoformat(),
                        },
                        "conversation_id": conversation.id,
                    }
                    yield f"data: {json.dumps(message_data)}\n\n"

                    # Generate title in background
                    if is_new_conversation:
                        background_tasks.add_task(
                            _generate_title_background,
                            conversation.id,
                            current_user.id,
                            chat_request.message,
                        )

        except AIException as e:
            logger.error(f"AI streaming error: {e.code} - {e.message}")
            yield f"data: {json.dumps({'type': 'error', 'error': e.message, 'code': e.code})}\n\n"
        except Exception as e:
            logger.exception("Unexpected streaming error")
            yield f"data: {json.dumps({'type': 'error', 'error': 'An unexpected error occurred'})}\n\n"

    return StreamingResponse(
        generate_sse(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )
