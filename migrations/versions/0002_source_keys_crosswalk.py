"""Key taxonomy rows by (source, external_id); add the ESCO-O*NET crosswalk and import log.

ESCO and O*NET occupations map many-to-many, so each source keeps its own rows and the
mapping lives in occupation_crosswalk instead of two ID columns on one row.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-17
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Tables are empty at this point (only smoke-test rows that clean up after themselves).
    for table, old_cols in (("skills", ("esco_uri", "onet_element_id")), ("occupations", ("esco_uri", "onet_soc_code"))):
        for col in old_cols:
            op.drop_column(table, col)
        op.add_column(table, sa.Column("source", sa.String(8), nullable=False))
        op.add_column(table, sa.Column("external_id", sa.Text(), nullable=False))
        op.create_unique_constraint(f"uq_{table}_source_external_id", table, ["source", "external_id"])
        op.create_check_constraint(f"ck_{table}_source", table, "source IN ('esco', 'onet')")
    op.add_column("occupations", sa.Column("code", sa.String(16)))
    op.create_index("ix_occupations_code", "occupations", ["code"])

    op.create_table(
        "occupation_crosswalk",
        sa.Column("onet_soc_code", sa.String(10), primary_key=True),
        sa.Column("esco_uri", sa.Text(), primary_key=True),
        sa.Column("match_type", sa.String(16), nullable=False),
    )
    op.create_index("ix_occupation_crosswalk_esco_uri", "occupation_crosswalk", ["esco_uri"])

    op.create_table(
        "taxonomy_imports",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("scope", sa.String(16), nullable=False),
        sa.Column("file_sha256", sa.String(64), nullable=False),
        sa.Column("row_counts", JSONB(), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("taxonomy_imports")
    op.drop_index("ix_occupation_crosswalk_esco_uri", table_name="occupation_crosswalk")
    op.drop_table("occupation_crosswalk")
    op.drop_index("ix_occupations_code", table_name="occupations")
    op.drop_column("occupations", "code")
    for table, old_cols in (("skills", (("esco_uri", sa.Text()), ("onet_element_id", sa.String(32)))),
                            ("occupations", (("esco_uri", sa.Text()), ("onet_soc_code", sa.String(10))))):
        op.drop_constraint(f"ck_{table}_source", table, type_="check")
        op.drop_constraint(f"uq_{table}_source_external_id", table, type_="unique")
        op.drop_column(table, "external_id")
        op.drop_column(table, "source")
        for name, type_ in old_cols:
            op.add_column(table, sa.Column(name, type_, unique=True))
