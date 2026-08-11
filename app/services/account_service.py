"""
Account lifecycle service — the single place that deletes a user's data.

Deleting an account touches every table that references ``users.id``. The
ORM relationships and DB-level ``ON DELETE CASCADE`` hints only help when the
underlying database enforces foreign keys (SQLite does not by default), so we
delete rows explicitly, child-first, inside one transaction. This guarantees a
full, consistent purge on every backend.
"""

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.models.conversation import Conversation, Message
from app.models.session import Session
from app.models.usage import UserUsage
from app.models.user import User

logger = get_logger(__name__)


async def delete_account(db: AsyncSession, user: User) -> None:
    """
    Permanently delete a user and all data they own.

    Order matters (child → parent) so foreign-key constraints hold whether or
    not the DB enforces ``ON DELETE CASCADE``:

        1. messages      (owned via conversations)
        2. conversations
        3. daily usage   (aggregate counters)
        4. sessions      (login records)
        5. user

    After this returns, every server-side session for the user is gone, so any
    token they held is immediately invalid.
    """
    user_id = user.id

    await db.execute(
        delete(Message).where(
            Message.conversation_id.in_(
                select(Conversation.id).where(Conversation.user_id == user_id)
            )
        )
    )
    await db.execute(delete(Conversation).where(Conversation.user_id == user_id))
    await db.execute(delete(UserUsage).where(UserUsage.user_id == user_id))
    await db.execute(delete(Session).where(Session.user_id == user_id))
    await db.execute(delete(User).where(User.id == user_id))

    await db.commit()

    # Audit record — deliberately minimal (no email/username) so the deletion
    # log itself carries no personally identifiable data.
    logger.info(
        "account.deleted",
        extra={
            "user_id": user_id,
            "environment": get_settings().environment,
        },
    )
