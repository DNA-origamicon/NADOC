"""Frozen protein–DNA molecular springs, independent of stage-specific restraints.

Only cross protein/DNA mutual traps are inherited: DNA relaxation traps and
absolute position restraints must not leak into free production or deposition.
"""
import re
import json
from pathlib import Path

FILENAME = "attachment_forces.txt"


def _blocks(text):
    for match in re.finditer(r"\{[^{}]*\}", text):
        fields = dict(re.findall(r"^\s*(\w+)\s*=\s*([^#\n]+)", match.group(), re.M))
        yield match.group(), {key: value.strip() for key, value in fields.items()}


def _counts(directory):
    header = (Path(directory) / "topology.top").read_text().splitlines()[0].split()
    return int(header[0]), int(header[3]) if len(header) >= 5 else 0


def molecular_blocks(text, directory):
    total, proteins = _counts(directory)
    result = {}
    for block, fields in _blocks(text):
        if fields.get("type") != "mutual_trap":
            continue
        a, b = int(fields["particle"]), int(fields["ref_particle"])
        if (a < proteins) == (b < proteins):
            continue
        if not (0 <= a < total and 0 <= b < total):
            raise ValueError("Protein–DNA attachment index is outside the frozen topology")
        if (a, b) in result and result[a, b] != block:
            raise ValueError("Conflicting protein–DNA attachment springs")
        result[a, b] = block
    for a, b in result:
        if (b, a) not in result:
            raise ValueError("Protein–DNA attachment is missing its reciprocal spring")
    return result


def attachment_text(directory):
    directory = Path(directory)
    for name in (FILENAME, "equil_forces.txt", "forces.txt"):
        path = directory / name
        if path.exists():
            found = molecular_blocks(path.read_text(), directory)
            if found or name == FILENAME:
                return "\n".join(found.values()) + ("\n" if found else "")
    return ""


def inherit_attachments(parent, child):
    parent, child = Path(parent), Path(child)
    text = attachment_text(parent)
    # Legacy continuations omitted springs. Recover evidence from an identical
    # frozen ancestor, without changing that ancestor or guessing new geometry.
    cursor, seen = parent, set()
    while not text and (cursor / "job.json").exists():
        ancestor = json.loads((cursor / "job.json").read_text()).get("parent_job_id")
        if not ancestor or ancestor in seen:
            break
        seen.add(ancestor)
        cursor = parent.parent / ancestor
        if not (cursor / "topology.top").exists() or (cursor / "topology.top").read_bytes() != (parent / "topology.top").read_bytes():
            break
        text = attachment_text(cursor)
    if text and (parent / "topology.top").read_bytes() != (child / "topology.top").read_bytes():
        raise ValueError("Cannot inherit attachments across different particle topologies")
    (child / FILENAME).write_text(text)


def compose_stage_forces(directory, stage_dir, protocol_path):
    """Compose after every force rewrite; never mutate the protocol force file."""
    text = attachment_text(directory)
    if not text:
        snapshot = Path(directory) / "design.json"
        if snapshot.exists() and _counts(directory)[1]:
            design = json.loads(snapshot.read_text())
            if any(a.get("visible", True) and a.get("binder_strand_id") and a.get("conjugation_atom_serial")
                   for a in design.get("protein_attachments", [])):
                raise ValueError("Protein–DNA attachment forces are missing; create a corrected continuation from the attached relaxation")
        return protocol_path
    springs = molecular_blocks(text, directory)
    protocol = Path(protocol_path).read_text() if protocol_path else ""
    # Remove the same molecular springs if already present (e.g. relaxation).
    for block, fields in _blocks(protocol):
        if fields.get("type") == "mutual_trap" and (
            int(fields["particle"]), int(fields["ref_particle"])
        ) in springs:
            protocol = protocol.replace(block, "")
    output = Path(stage_dir) / "effective_forces.txt"
    output.write_text(protocol + "\n" + text)
    return output.resolve()
