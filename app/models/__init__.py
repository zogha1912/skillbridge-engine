# Import every model here so Alembic sees it on Base.metadata.
from app.models.taxonomy import Occupation, OccupationCrosswalk, OccupationSkill, Skill, TaxonomyImport

__all__ = ["Occupation", "OccupationCrosswalk", "OccupationSkill", "Skill", "TaxonomyImport"]
