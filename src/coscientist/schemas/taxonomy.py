from pydantic import BaseModel, Field


class InducedFamily(BaseModel):
    canonical_name: str
    description: str | None = None
    keywords: list[str] = Field(default_factory=list)
    related_to: list[str] = Field(default_factory=list)


class AgentTaxonomyOutput(BaseModel):
    families: list[InducedFamily] = Field(default_factory=list)


class TaxonomyDeriveRequest(BaseModel):
    top_k: int = 30
    max_families: int = 12
    dry_run: bool = False
    pinned: list[str] = Field(default_factory=list)


class TaxonomyDeriveResult(BaseModel):
    goal_id: str
    workspace_id: str
    dry_run: bool
    chunks_sampled: int
    papers_sampled: int
    families: list[InducedFamily]
    terms_created: int
    relationships_created: int


# Claude tool schema — the model must return the method-family taxonomy actually
# present in the sampled corpus for a specific goal.
RECORD_TAXONOMY_TOOL = {
    "name": "record_taxonomy",
    "description": (
        "Record the method-family taxonomy induced from the supplied corpus "
        "chunks for one research goal."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "families": {
                "type": "array",
                "description": "The distinct method families actually present in the corpus.",
                "items": {
                    "type": "object",
                    "properties": {
                        "canonical_name": {
                            "type": "string",
                            "description": "snake_case identifier, e.g. parametric_array_loudspeaker",
                        },
                        "description": {
                            "type": "string",
                            "description": "One-sentence description grounded in the chunks.",
                        },
                        "keywords": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Lowercase surface forms that appear in the chunk text.",
                        },
                        "related_to": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Other canonical_names in this list that are related.",
                        },
                    },
                    "required": ["canonical_name", "keywords"],
                },
            },
        },
        "required": ["families"],
    },
}
