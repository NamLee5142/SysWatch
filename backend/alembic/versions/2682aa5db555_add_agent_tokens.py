"""add agent tokens

A new table, so this is a create rather than an alter: no existing row is
touched and no data is rewritten. An install that never adds a second machine
carries an empty table and is otherwise unaffected.

Nothing is seeded. A credential that exists without somebody deciding it should
is a credential nobody revokes.

Revision ID: 2682aa5db555
Revises: 3b56cfe52aaf
Create Date: 2026-09-07 23:03:00.526499

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2682aa5db555'
down_revision: Union[str, Sequence[str], None] = '3b56cfe52aaf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('agent_tokens',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('host_name', sa.String(length=255), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('description', sa.String(length=255), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_agent_tokens')),
    sa.UniqueConstraint('token_hash', name=op.f('uq_agent_tokens_token_hash'))
    )
    with op.batch_alter_table('agent_tokens', schema=None) as batch_op:
        batch_op.create_index('ix_agent_tokens_host_name', ['host_name'], unique=False)



def downgrade() -> None:
    with op.batch_alter_table('agent_tokens', schema=None) as batch_op:
        batch_op.drop_index('ix_agent_tokens_host_name')

    op.drop_table('agent_tokens')
