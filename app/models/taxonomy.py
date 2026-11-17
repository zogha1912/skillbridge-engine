from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Identity,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

# Gemini embeddings are requested at 768 dimensions: small enough for Neon's free
# storage and well under pgvector's 2,000-dimension HNSW index limit.
EMBEDDING_DIM = 768


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Skill(TimestampMixin, Base):
    """A skill, knowledge area or technology from ESCO or O*NET.

    external_id is the ESCO concept URI, the O*NET element ID, or "tech:<name>" for
    O*NET technology examples.
    """

    __tablename__ = "skills"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    source: Mapped[str] = mapped_column(String(8), nullable=False)
    external_id: Mapped[str] = mapped_column(Text, nullable=False)
    preferred_label: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    skill_type: Mapped[str | None] = mapped_column(String(32))
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))

    occupations: Mapped[list["OccupationSkill"]] = relationship(back_populates="skill")

    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_skills_source_external_id"),
        CheckConstraint("source IN ('esco', 'onet')", name="ck_skills_source"),
        Index(
            "ix_skills_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )


class Occupation(TimestampMixin, Base):
    """A target role profile (S_target) from ESCO or O*NET.

    external_id is the ESCO concept URI or the O*NET-SOC code; code is the ESCO/ISCO
    code or the O*NET-SOC code, used for scope filters such as ICT roles.
    """

    __tablename__ = "occupations"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    source: Mapped[str] = mapped_column(String(8), nullable=False)
    external_id: Mapped[str] = mapped_column(Text, nullable=False)
    code: Mapped[str | None] = mapped_column(String(16), index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))

    skills: Mapped[list["OccupationSkill"]] = relationship(back_populates="occupation")

    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_occupations_source_external_id"),
        CheckConstraint("source IN ('esco', 'onet')", name="ck_occupations_source"),
        Index(
            "ix_occupations_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )


class OccupationSkill(Base):
    """Links a role to a skill, with how much the role depends on it."""

    __tablename__ = "occupation_skills"

    occupation_id: Mapped[int] = mapped_column(
        ForeignKey("occupations.id", ondelete="CASCADE"), primary_key=True
    )
    skill_id: Mapped[int] = mapped_column(
        ForeignKey("skills.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    relation: Mapped[str] = mapped_column(String(16), nullable=False)
    importance: Mapped[float | None] = mapped_column(Float)  # O*NET importance rescaled to 0..1
    source: Mapped[str] = mapped_column(String(8), nullable=False)

    occupation: Mapped[Occupation] = relationship(back_populates="skills")
    skill: Mapped[Skill] = relationship(back_populates="occupations")

    __table_args__ = (
        CheckConstraint("relation IN ('essential', 'optional')", name="ck_occupation_skills_relation"),
        CheckConstraint("source IN ('esco', 'onet')", name="ck_occupation_skills_source"),
        CheckConstraint("importance IS NULL OR importance BETWEEN 0 AND 1", name="ck_occupation_skills_importance"),
    )


class OccupationCrosswalk(Base):
    """Official ESCO <-> O*NET occupation mapping (many-to-many), keyed by external IDs."""

    __tablename__ = "occupation_crosswalk"

    onet_soc_code: Mapped[str] = mapped_column(String(10), primary_key=True)
    esco_uri: Mapped[str] = mapped_column(Text, primary_key=True, index=True)
    match_type: Mapped[str] = mapped_column(String(16), nullable=False)


class TaxonomyImport(Base):
    """One row per import run: provenance for attribution and reproducibility."""

    __tablename__ = "taxonomy_imports"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    scope: Mapped[str] = mapped_column(String(16), nullable=False)
    file_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    row_counts: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
