"""Stable-identity parser and numeric comparator for native VR scene v6-v10.

This module deliberately knows nothing about OpenXR or rendering. It compares the
model-space scene contract before the native viewer normalizes it into metres, making
topology/geometry regressions deterministic and attributable to a semantic owner.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from math import acos, degrees
from urllib.parse import unquote

import numpy as np


_VALUE_COUNTS = {"P": 16, "C": 19, "H": 19, "B": 24, "K": 3}


@dataclass(frozen=True, slots=True)
class ScenePrimitive:
    representation: str
    record_type: str
    identity: str
    values: tuple[float, ...]
    owner_aliases: tuple[str, ...] = ()
    transform_owners: tuple[tuple[str, float, float], ...] = ()


@dataclass(frozen=True, slots=True)
class SceneTolerance:
    position_nm: float = 1e-6
    dimension_nm: float = 1e-6
    orientation_deg: float = 1e-5
    color: float = 1e-6


@dataclass(frozen=True, slots=True)
class SceneDifference:
    representation: str
    identity: str
    category: str
    detail: str

    def __str__(self) -> str:
        owner = unquote(self.identity)
        return f"{self.representation}/{owner}: {self.category}: {self.detail}"


@dataclass(frozen=True, slots=True)
class SceneComparison:
    matched_primitives: int
    differences: tuple[SceneDifference, ...]

    @property
    def ok(self) -> bool:
        return not self.differences

    def summary(self, limit: int = 20) -> str:
        if self.ok:
            return (
                f"VR scene parity passed ({self.matched_primitives} primitives matched)"
            )
        shown = [str(difference) for difference in self.differences[:limit]]
        remaining = len(self.differences) - len(shown)
        if remaining:
            shown.append(f"... {remaining} more difference(s)")
        return "VR scene parity failed:\n" + "\n".join(f"- {line}" for line in shown)


def parse_scene_contract(text: str) -> dict[str, dict[str, ScenePrimitive]]:
    """Parse stable natural/expanded poses into ``pose/representation → primitives``."""
    lines = text.splitlines()
    if not lines:
        raise ValueError("empty VR scene")
    header = lines[0].split()
    if (
        len(header) != 4
        or header[0] != "NADOCVR"
        or header[1] not in {"6", "7", "8", "9", "10"}
    ):
        raise ValueError("stable comparison requires NADOCVR v6 through v10")
    version = int(header[1])
    result: dict[str, dict[str, ScenePrimitive]] = {}
    active: str | None = None
    for line_number, line in enumerate(lines[1:], start=2):
        fields = line.split()
        if not fields or fields[0].startswith("#"):
            continue
        if fields[0] in {"R", "E"}:
            if len(fields) != 2:
                raise ValueError(f"line {line_number}: malformed representation record")
            if fields[0] == "E" and version < 7:
                raise ValueError(f"line {line_number}: expanded pose requires v7")
            active = fields[1] if fields[0] == "R" else f"expanded/{fields[1]}"
            if active in result:
                raise ValueError(
                    f"line {line_number}: duplicate representation {active}"
                )
            result[active] = {}
            continue
        if fields[0] == "A":
            if version < 8:
                raise ValueError(f"line {line_number}: owner aliases require v8")
            if active is None:
                raise ValueError(f"line {line_number}: owner aliases before representation")
            if len(fields) < 3:
                raise ValueError(f"line {line_number}: malformed owner aliases")
            identity = fields[1]
            try:
                alias_count = int(fields[2])
            except ValueError as error:
                raise ValueError(
                    f"line {line_number}: invalid owner alias count"
                ) from error
            aliases = tuple(fields[3:])
            if alias_count < 1 or alias_count > 8 or len(aliases) != alias_count:
                raise ValueError(f"line {line_number}: invalid owner alias count")
            if any(len(alias) > 2048 for alias in aliases):
                raise ValueError(f"line {line_number}: owner alias is too long")
            primitive = result[active].get(identity)
            if primitive is None:
                raise ValueError(
                    f"line {line_number}: owner aliases reference unknown identity {identity}"
                )
            if primitive.owner_aliases:
                raise ValueError(
                    f"line {line_number}: duplicate owner aliases for {identity}"
                )
            if len(set(aliases)) != len(aliases):
                raise ValueError(f"line {line_number}: duplicate owner alias")
            result[active][identity] = replace(primitive, owner_aliases=aliases)
            continue
        if fields[0] == "T":
            if version < 10:
                raise ValueError(f"line {line_number}: transform owners require v10")
            if active is None:
                raise ValueError(f"line {line_number}: transform owners before representation")
            if len(fields) < 6:
                raise ValueError(f"line {line_number}: malformed transform owners")
            identity = fields[1]
            try:
                owner_count = int(fields[2])
            except ValueError as error:
                raise ValueError(
                    f"line {line_number}: invalid transform owner count"
                ) from error
            primitive = result[active].get(identity)
            if primitive is None:
                raise ValueError(
                    f"line {line_number}: transform owners reference unknown identity {identity}"
                )
            if primitive.transform_owners:
                raise ValueError(
                    f"line {line_number}: duplicate transform owners for {identity}"
                )
            if owner_count < 1 or owner_count > 8 or len(fields) != 3 + owner_count * 3:
                raise ValueError(f"line {line_number}: invalid transform owner count")
            owners = []
            for index in range(owner_count):
                token = fields[3 + index * 3]
                try:
                    start_weight = float(fields[4 + index * 3])
                    end_weight = float(fields[5 + index * 3])
                except ValueError as error:
                    raise ValueError(
                        f"line {line_number}: invalid transform owner weight"
                    ) from error
                if (
                    not token
                    or len(token) > 2048
                    or not np.all(np.isfinite([start_weight, end_weight]))
                    or not 0.0 <= start_weight <= 1.0
                    or not 0.0 <= end_weight <= 1.0
                ):
                    raise ValueError(f"line {line_number}: invalid transform owner")
                owners.append((token, start_weight, end_weight))
            if len({owner[0] for owner in owners}) != len(owners):
                raise ValueError(f"line {line_number}: duplicate transform owner")
            result[active][identity] = replace(
                primitive, transform_owners=tuple(owners)
            )
            continue
        record_type = fields[0]
        if record_type not in _VALUE_COUNTS:
            raise ValueError(f"line {line_number}: unknown record {record_type}")
        if active is None:
            raise ValueError(f"line {line_number}: primitive before representation")
        if record_type == "K" and version < 9:
            raise ValueError(f"line {line_number}: cluster handles require v9")
        expected_fields = _VALUE_COUNTS[record_type] + 2
        if len(fields) != expected_fields:
            raise ValueError(
                f"line {line_number}: {record_type} needs {expected_fields} fields, "
                f"got {len(fields)}"
            )
        identity = fields[1]
        if identity in result[active]:
            raise ValueError(
                f"line {line_number}: duplicate identity {identity} in {active}"
            )
        try:
            values = tuple(float(value) for value in fields[2:])
        except ValueError as error:
            raise ValueError(
                f"line {line_number}: non-numeric primitive value"
            ) from error
        if not np.all(np.isfinite(values)):
            raise ValueError(f"line {line_number}: non-finite primitive value")
        result[active][identity] = ScenePrimitive(
            representation=active,
            record_type=record_type,
            identity=identity,
            values=values,
        )
    if not result or not any(result.values()):
        raise ValueError("VR scene contains no primitives")
    return result


def parse_scene_v6(text: str) -> dict[str, dict[str, ScenePrimitive]]:
    """Backward-compatible strict v6 entry point used by existing fixtures."""
    header = text.splitlines()[0].split() if text.splitlines() else []
    if len(header) < 2 or header[1] != "6":
        raise ValueError("stable comparison requires NADOCVR v6")
    return parse_scene_contract(text)


def _norm(vector) -> float:
    return float(np.linalg.norm(np.asarray(vector, dtype=float)))


def _angle_degrees(first, second) -> float:
    first_array, second_array = np.asarray(first), np.asarray(second)
    first_norm, second_norm = _norm(first_array), _norm(second_array)
    if first_norm < 1e-12 or second_norm < 1e-12:
        return 0.0 if first_norm < 1e-12 and second_norm < 1e-12 else 180.0
    cosine = float(np.dot(first_array, second_array) / (first_norm * second_norm))
    return degrees(acos(np.clip(cosine, -1.0, 1.0)))


def _numeric_differences(
    expected: ScenePrimitive,
    actual: ScenePrimitive,
    tolerance: SceneTolerance,
) -> list[tuple[str, str]]:
    first, second = expected.values, actual.values
    differences = []
    if expected.record_type == "K":
        position_error = _norm(np.subtract(first[0:3], second[0:3]))
        if position_error > tolerance.position_nm:
            differences.append(("position", f"handle error {position_error:.6g} nm"))
        return differences
    if expected.record_type == "P":
        position_error = _norm(np.subtract(first[0:3], second[0:3]))
        if position_error > tolerance.position_nm:
            differences.append(("position", f"error {position_error:.6g} nm"))
        dimension_error = abs(first[3] - second[3])
        if dimension_error > tolerance.dimension_nm:
            differences.append(("dimension", f"radius error {dimension_error:.6g} nm"))
        color_start = 4
    elif expected.record_type in {"C", "H"}:
        start_error = _norm(np.subtract(first[0:3], second[0:3]))
        end_error = _norm(np.subtract(first[3:6], second[3:6]))
        position_error = max(start_error, end_error)
        if position_error > tolerance.position_nm:
            differences.append(("position", f"endpoint error {position_error:.6g} nm"))
        angle_error = _angle_degrees(
            np.subtract(first[3:6], first[0:3]),
            np.subtract(second[3:6], second[0:3]),
        )
        if angle_error > tolerance.orientation_deg:
            differences.append(("orientation", f"axis error {angle_error:.6g}°"))
        dimension_error = abs(first[6] - second[6])
        if dimension_error > tolerance.dimension_nm:
            differences.append(("dimension", f"radius error {dimension_error:.6g} nm"))
        color_start = 7
    else:
        center_error = _norm(np.subtract(first[0:3], second[0:3]))
        if center_error > tolerance.position_nm:
            differences.append(("position", f"center error {center_error:.6g} nm"))
        for axis_index, label in enumerate("xyz"):
            offset = 3 + axis_index * 3
            expected_axis, actual_axis = (
                first[offset : offset + 3],
                second[offset : offset + 3],
            )
            dimension_error = abs(_norm(expected_axis) - _norm(actual_axis))
            if dimension_error > tolerance.dimension_nm:
                differences.append(
                    ("dimension", f"axis {label} length error {dimension_error:.6g} nm")
                )
            angle_error = _angle_degrees(expected_axis, actual_axis)
            if angle_error > tolerance.orientation_deg:
                differences.append(
                    ("orientation", f"axis {label} error {angle_error:.6g}°")
                )
        color_start = 12
    color_error = max(
        abs(expected_value - actual_value)
        for expected_value, actual_value in zip(
            first[color_start:], second[color_start:]
        )
    )
    if color_error > tolerance.color:
        differences.append(("color", f"channel error {color_error:.6g}"))
    return differences


def compare_scenes(
    expected_text: str,
    actual_text: str,
    tolerance: SceneTolerance = SceneTolerance(),
) -> SceneComparison:
    """Compare two stable scene contracts by semantic identity."""
    expected = parse_scene_contract(expected_text)
    actual = parse_scene_contract(actual_text)
    differences: list[SceneDifference] = []
    matched = 0
    for representation in sorted(set(expected) | set(actual)):
        expected_primitives = expected.get(representation, {})
        actual_primitives = actual.get(representation, {})
        for identity in sorted(set(expected_primitives) - set(actual_primitives)):
            differences.append(
                SceneDifference(
                    representation, identity, "missing", "primitive is absent"
                )
            )
        for identity in sorted(set(actual_primitives) - set(expected_primitives)):
            differences.append(
                SceneDifference(
                    representation, identity, "unexpected", "primitive was added"
                )
            )
        for identity in sorted(set(expected_primitives) & set(actual_primitives)):
            expected_primitive = expected_primitives[identity]
            actual_primitive = actual_primitives[identity]
            if expected_primitive.record_type != actual_primitive.record_type:
                differences.append(
                    SceneDifference(
                        representation,
                        identity,
                        "type",
                        f"expected {expected_primitive.record_type}, got {actual_primitive.record_type}",
                    )
                )
                continue
            matched += 1
            if expected_primitive.owner_aliases != actual_primitive.owner_aliases:
                differences.append(
                    SceneDifference(
                        representation,
                        identity,
                        "owner",
                        "canonical owner aliases differ",
                    )
                )
            if expected_primitive.transform_owners != actual_primitive.transform_owners:
                differences.append(
                    SceneDifference(
                        representation,
                        identity,
                        "transform_owner",
                        "endpoint transform ownership differs",
                    )
                )
            differences.extend(
                SceneDifference(representation, identity, category, detail)
                for category, detail in _numeric_differences(
                    expected_primitive, actual_primitive, tolerance
                )
            )
    return SceneComparison(matched, tuple(differences))
