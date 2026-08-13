"""Add the public PR annotation workbench.

Revision ID: 20260812_0002
Revises: 20260811_0001
Create Date: 2026-08-12
"""
from typing import Sequence, Union

from alembic import op

from codeevo.database import (
    annotation_adjudications,
    annotation_cases,
    annotation_exports,
    annotation_submissions,
)


revision: str = "20260812_0002"
down_revision: Union[str, None] = "20260811_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    for table in (
        annotation_cases,
        annotation_submissions,
        annotation_adjudications,
        annotation_exports,
    ):
        table.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for table in (
        annotation_exports,
        annotation_adjudications,
        annotation_submissions,
        annotation_cases,
    ):
        table.drop(bind=bind, checkfirst=True)
