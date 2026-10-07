"""Claims: every dossier statement says how it is known.

Dossify generates only ``observed`` and ``derived`` claims.  ``user_asserted``
and ``disputed`` claims come from the owner's private claims file.  ``inferred``
exists in the vocabulary so a claim can be recorded honestly, but Dossify never
produces one, and the predicates below are refused outright.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ClaimType = Literal["observed", "derived", "inferred", "user_asserted", "disputed", "unknown"]

# Conclusions too unreliable or sensitive to generate: the evidence may be
# reported, the conclusion may not.
FORBIDDEN_PREDICATES = (
    "medical_diagnosis", "mental_health", "political_belief", "religious_belief",
    "relationship_status", "relationship_closeness", "sleep_from_inactivity",
    "exercise_type", "productivity", "emotional_state", "criminal_behaviour",
)


class Claim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: str = "self"
    predicate: str
    value: str
    claim_type: ClaimType
    valid_from: date | None = None
    valid_to: date | None = None
    evidence: list[str] = Field(default_factory=list)
    coverage: str | None = None
    algorithm: str | None = None
    status: Literal["active", "retired"] = "active"

    @field_validator("predicate")
    @classmethod
    def allowed(cls, value: str) -> str:
        if value in FORBIDDEN_PREDICATES:
            raise ValueError(f"{value} is a forbidden inference and cannot be a claim")
        return value


def load_user_claims(path: Path | None) -> list[Claim]:
    """Read the owner's claims; only user_asserted and disputed are accepted."""
    if not path or not path.exists():
        return []
    claims = [Claim.model_validate(item) for item in json.loads(path.read_text(encoding="utf-8"))]
    for claim in claims:
        if claim.claim_type not in ("user_asserted", "disputed"):
            raise ValueError(
                f"{path.name}: {claim.predicate} is {claim.claim_type}; the claims file holds "
                "only user_asserted or disputed claims")
    return claims
