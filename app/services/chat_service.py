"""
Chat service for handling conversations and AI interactions.

This service manages conversation creation, message persistence, and
conversation retrieval. AI orchestration is handled separately by
app.services.ai_orchestrator.
"""

from typing import List, Optional, Union

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload, lazyload

from app.models.conversation import Conversation, Message
from app.models.user import User
from app.schemas.conversation import ConversationCreate, ConversationUpdate


class ChatService:
    """Service for managing conversations and chat message persistence."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_conversation(self, user: User, conv_data: ConversationCreate) -> Conversation:
        """
        Create a new conversation for a user.
        """
        conversation = Conversation(
            user_id=user.id,
            title=conv_data.title,
        )
        self.db.add(conversation)
        await self.commit_and_refresh(conversation)
        return conversation

    async def get_user_conversations(
        self, user: User, skip: int = 0, limit: int = 50
    ) -> List[Conversation]:
        """
        Get conversations for a user, ordered by most recently updated.
        """
        result = await self.db.execute(
            select(Conversation)
            .where(Conversation.user_id == user.id)
            .order_by(Conversation.updated_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_conversation(
        self,
        conversation_id: int,
        user: Union[User, int],
        message_limit: Optional[int] = None,
    ) -> Optional[Conversation]:
        """
        Get a specific conversation by ID and owner.

        ``message_limit`` bounds the number of messages loaded:

        * **None** — load all messages (internal callers, summarisation).
        * **0** — load no messages (update/delete endpoints).
        * **N > 0** — load the most recent N messages (GET endpoint, chat).

        `user` may be a User object or a user_id integer. The integer form is
        useful in background tasks where a full User ORM object is unavailable.
        """
        user_id = user if isinstance(user, int) else user.id

        if message_limit == 0:
            # Bypass message loading entirely.
            result = await self.db.execute(
                select(Conversation)
                .where(Conversation.id == conversation_id, Conversation.user_id == user_id)
            )
        elif message_limit is None:
            # Load all messages (selectinload — for summarisation / history).
            result = await self.db.execute(
                select(Conversation)
                .where(Conversation.id == conversation_id, Conversation.user_id == user_id)
                .options(selectinload(Conversation.messages))
            )
        else:
            # Load conversation without messages, then fetch the latest N.
            result = await self.db.execute(
                select(Conversation)
                .where(Conversation.id == conversation_id, Conversation.user_id == user_id)
                .options(lazyload(Conversation.messages))
            )

        conversation = result.scalar_one_or_none()
        if conversation is None:
            return None

        if message_limit is not None and message_limit > 0:
            msg_result = await self.db.execute(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.created_at.desc())
                .limit(message_limit)
            )
            # Store in chronological order (reversed from desc query).
            conversation.messages = list(reversed(msg_result.scalars().all()))

        return conversation

    async def get_recent_messages(
        self,
        conversation_id: int,
        user: Union[User, int],
        limit: int = 50,
    ) -> List[Message]:
        """
        Get recent messages for a conversation.

        This supports context-window construction without loading unlimited
        message history in future call sites.
        """
        user_id = user if isinstance(user, int) else user.id

        # Ensure conversation belongs to user first.
        conv_result = await self.db.execute(
            select(Conversation.id).where(
                Conversation.id == conversation_id,
                Conversation.user_id == user_id,
            )
        )
        if conv_result.scalar_one_or_none() is None:
            return []

        result = await self.db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
        # Query is newest-first for efficient limiting; return chronological order.
        return list(reversed(result.scalars().all()))

    async def update_conversation(
        self, conversation: Conversation, conv_data: ConversationUpdate
    ) -> Conversation:
        """
        Update a conversation's metadata.
        """
        if conv_data.title is not None:
            conversation.title = conv_data.title
        await self.commit_and_refresh(conversation)
        return conversation

    async def delete_conversation(self, conversation: Conversation) -> None:
        """
        Delete a conversation and all its messages.
        """
        await self.db.delete(conversation)
        await self.db.commit()

    async def add_message(
        self, conversation: Conversation, role: str, content: str, *, commit: bool = True
    ) -> Message:
        """
        Add a message to a conversation.

        When ``commit`` is False the message is added to the session but not
        flushed or committed — useful for batching a user+assistant message
        pair into a single transaction.
        """
        message = Message(
            conversation_id=conversation.id,
            role=role,
            content=content,
        )
        self.db.add(message)
        if commit:
            await self.commit_and_refresh(message)
        return message

    async def count_user_conversations(self, user_id: int) -> int:
        """Return the total number of conversations for a user (for pagination headers)."""
        result = await self.db.execute(
            select(func.count(Conversation.id)).where(Conversation.user_id == user_id)
        )
        return int(result.scalar_one() or 0)

    async def count_messages(self, conversation_id: int) -> int:
        """Count messages in a conversation."""
        result = await self.db.execute(
            select(func.count(Message.id)).where(Message.conversation_id == conversation_id)
        )
        return int(result.scalar_one() or 0)

    async def commit_and_refresh(self, obj) -> None:
        """Commit changes and refresh object from database."""
        await self.db.commit()
        await self.db.refresh(obj)
