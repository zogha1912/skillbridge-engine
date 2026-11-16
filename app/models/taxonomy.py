from datetime import datetime

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
    func,
)
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
    """A skill or knowledge item from ESCO and/or O*NET."""

    __tablename__ = "skills"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    esco_uri: Mapped[str | None] = mapped_column(Text, unique=True)
    onet_element_id: Mapped[str | None] = mapped_column(String(32), unique=True)
    preferred_label: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    skill_type: Mapped[str | None] = mapped_column(String(32))
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))

    occupations: Mapped[list["OccupationSkill"]] = relationship(back_populates="skill")

    __table_args__ = (
        Index(
            "ix_skills_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )


class Occupation(TimestampMixin, Base):
    """A target role profile (S_target) from ESCO and/or O*NET."""

    __tablename__ = "occupations"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    esco_uri: Mapped[str | None] = mapped_column(Text, unique=True)
    onet_soc_code: Mapped[str | None] = mapped_column(String(10), unique=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))

    skills: Mapped[list["OccupationSkill"]] = relationship(back_populates="occupation")

    __table_args__ = (
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
