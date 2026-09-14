"""hold an alert open until it settles

One nullable column, so this is an O(1) ADD COLUMN: no row is rewritten and the
table is not copied, whatever its size.

Null on every existing row, which is exactly right - null means "currently
breaching", and every open alert is. A closed alert never reads it.

Revision ID: 1568ad235f5f
Revises: 2682aa5db555
Create Date: 2026-09-08 16:37:56.636562

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1568ad235f5f'
down_revision: Union[str, Sequence[str], None] = '2682aa5db555'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('alerts', schema=None) as batch_op:
        batch_op.add_column(sa.Column('clearing_since', sa.DateTime(timezone=True), nullable=True))



def downgrade() -> None:
    with op.batch_alter_table('alerts', schema=None) as batch_op:
        batch_op.drop_column('clearing_since')

