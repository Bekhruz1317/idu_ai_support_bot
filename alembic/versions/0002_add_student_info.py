"""add student_info

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-30

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "student_info",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("first_name", sa.String(), nullable=True),
        sa.Column("last_name", sa.String(), nullable=True),
        sa.Column("group", sa.String(), nullable=True),
        sa.Column("student_id", sa.String(), nullable=True),
        sa.Column("lms_username", sa.String(), nullable=True),
        sa.Column("srs_username", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("student_info")
