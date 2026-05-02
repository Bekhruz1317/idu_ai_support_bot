"""add response_time to logs

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-02

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("logs") as batch_op:
        batch_op.add_column(sa.Column("response_time", sa.Float(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("logs") as batch_op:
        batch_op.drop_column("response_time")
