"""add email to student_info

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-30

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("student_info") as batch_op:
        batch_op.add_column(sa.Column("email", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("student_info") as batch_op:
        batch_op.drop_column("email")
