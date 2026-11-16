# Import every model here so Alembic sees it on Base.metadata.
from app.models.taxonomy import Occupation, OccupationSkill, Skill

__all__ = ["Occupation", "OccupationSkill", "Skill"]
