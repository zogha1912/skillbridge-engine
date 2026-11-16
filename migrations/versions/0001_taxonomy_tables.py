"""Enable pgvector and create the ESCO / O*NET taxonomy tables.

Revision ID: 0001
Revises:
Create Date: 2026-11-06
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBEDDING_DIM = 768


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "skills",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("esco_uri", sa.Text(), unique=True),
        sa.Column("onet_element_id", sa.String(32), unique=True),
        sa.Column("preferred_label", sa.Text(), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("skill_type", sa.String(32)),
        sa.Column("embedding", Vector(EMBEDDING_DIM)),
        *_timestamps(),
    )
    op.create_index(
        "ix_skills_embedding_hnsw",
        "skills",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )

    op.create_table(
        "occupations",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("esco_uri", sa.Text(), unique=True),
        sa.Column("onet_soc_code", sa.String(10), unique=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("embedding", Vector(EMBEDDING_DIM)),
        *_timestamps(),
    )
    op.create_index(
        "ix_occupations_embedding_hnsw",
        "occupations",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )

    op.create_table(
        "occupation_skills",
        sa.Column(
            "occupation_id",
            sa.BigInteger(),
            sa.ForeignKey("occupations.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "skill_id",
            sa.BigInteger(),
            sa.ForeignKey("skills.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("relation", sa.String(16), nullable=False),
        sa.Column("importance", sa.Float()),
        sa.Column("source", sa.String(8), nullable=False),
        sa.CheckConstraint("relation IN ('essential', 'optional')", name="ck_occupation_skills_relation"),
        sa.CheckConstraint("source IN ('esco', 'onet')", name="ck_occupation_skills_source"),
        sa.CheckConstraint(
            "importance IS NULL OR importance BETWEEN 0 AND 1", name="ck_occupation_skills_importance"
        ),
    )
    op.create_index("ix_occupation_skills_skill_id", "occupation_skills", ["skill_id"])


def downgrade() -> None:
    op.drop_index("ix_occupation_skills_skill_id", table_name="occupation_skills")
    op.drop_table("occupation_skills")
    op.drop_index("ix_occupations_embedding_hnsw", table_name="occupations")
    op.drop_table("occupations")
    op.drop_index("ix_skills_embedding_hnsw", table_name="skills")
    op.drop_table("skills")
    # The vector extension is left installed; other databases objects may depend on it.
