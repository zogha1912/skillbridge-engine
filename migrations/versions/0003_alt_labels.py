"""Add alt_labels (alternative names) to skills and occupations.

ESCO lists synonyms such as "application developer" for "software developer"; they are
needed to recognise skills written in different words (résumé parsing, embeddings).

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-17
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table in ("skills", "occupations"):
        op.add_column(table, sa.Column("alt_labels", ARRAY(sa.Text())))


def downgrade() -> None:
    for table in ("skills", "occupations"):
        op.drop_column(table, "alt_labels")
