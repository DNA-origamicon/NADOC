"""Replay contract for the existing contextual CPD conversion operation.

This records the inputs and exact placement implementation, never the resulting
atoms as a substitute for construction. It does not promote model qualification.
"""

import hashlib
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

ROOT = Path(__file__).resolve().parents[2]
FILES = (
    "backend/core/part_cpd_conversion_isomers.py",
    "backend/core/cpd_conversion.py",
    "backend/core/cpd_six_residue.py",
    "backend/core/cpd_product.py",
    "backend/core/atomistic.py",
    "backend/core/atomistic_helpers.py",
    "backend/core/base_keys.py",
    "backend/core/photoproduct_chemistry.py",
    "backend/data/cpd_conversion_cores.json",
    "backend/data/cpd_six_residue_seeds.json",
)


class ConversionCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    proof_version: Literal[1] = Field(alias="_proof_version")
    conversion_version: Literal[3]
    method: Literal["bases-only"]
    base_keys: list[str] = Field(min_length=2, max_length=2)
    stereochemistry: Literal["cis-syn", "cis-anti-I", "trans-syn-I", "trans-syn-II"]
    history_seed: str
    implementation: dict[str, str]

    @field_validator("history_seed")
    @classmethod
    def seed(cls, value):
        if str(UUID(value)) != value:
            raise ValueError("Expected a canonical UUID")
        return value


def pins():
    return {
        name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in FILES
    }


def prepare(keys, seed, stereochemistry):
    return ConversionCommand.model_validate(
        {
            "_proof_version": 1,
            "conversion_version": 3,
            "method": "bases-only",
            "base_keys": list(keys),
            "stereochemistry": stereochemistry,
            "history_seed": seed,
            "implementation": pins(),
        }
    ).model_dump(by_alias=True)


def build(design, params):
    command = ConversionCommand.model_validate(params)
    if command.implementation != pins():
        raise ValueError(
            "CPD conversion implementation changed; explicit recipe migration is required"
        )
    if design.atomistic_reference is not None:
        raise ValueError(
            "Recorded CPD conversion requires authored native atoms, not an atomistic reference"
        )
    from backend.core.cpd_conversion import convert_thymine_pair

    updated, _ = convert_thymine_pair(
        design,
        command.base_keys,
        command.stereochemistry,
        identity_seed=command.history_seed,
    )
    if command.implementation != pins():
        raise ValueError("CPD conversion implementation changed during construction")
    return updated
