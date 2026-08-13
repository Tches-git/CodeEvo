"""Create the CodeEvo production schema.

Revision ID: 20260811_0001
Revises: None
Create Date: 2026-08-11
"""
from typing import Sequence, Union

from alembic import op

from codeevo.database import metadata


revision: str = "20260811_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    metadata.create_all(bind=bind, checkfirst=True)

    # Databases created by CodeEvo 0.1 used startup DDL instead of Alembic.
    # These idempotent additions let that schema be stamped and upgraded safely.
    if bind.dialect.name == "postgresql":
        statements = (
            "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS "
            "tenant_id TEXT NOT NULL DEFAULT 'default'",
            "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS "
            "cancel_requested BOOLEAN NOT NULL DEFAULT FALSE",
            "ALTER TABLE installations ADD COLUMN IF NOT EXISTS "
            "tenant_id TEXT NOT NULL DEFAULT 'default'",
            "ALTER TABLE skill_artifact_versions ADD COLUMN IF NOT EXISTS "
            "tenant_id TEXT NOT NULL DEFAULT 'default'",
            "ALTER TABLE skill_evolution_runs ADD COLUMN IF NOT EXISTS "
            "tenant_id TEXT NOT NULL DEFAULT 'default'",
            "ALTER TABLE deployments ADD COLUMN IF NOT EXISTS "
            "max_disagreement_rate DOUBLE PRECISION NOT NULL DEFAULT .2",
            "ALTER TABLE deployments ADD COLUMN IF NOT EXISTS "
            "auto_promote BOOLEAN NOT NULL DEFAULT FALSE",
            "ALTER TABLE deployments ADD COLUMN IF NOT EXISTS "
            "shadow_samples INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE deployments ADD COLUMN IF NOT EXISTS "
            "disagreements INTEGER NOT NULL DEFAULT 0",
        )
        for statement in statements:
            op.execute(statement)


def downgrade() -> None:
    metadata.drop_all(bind=op.get_bind(), checkfirst=True)
