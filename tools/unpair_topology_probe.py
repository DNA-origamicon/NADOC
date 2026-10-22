"""Read-only unpairing exploration, never a production command or geometry seed.

Remove pair edges in a detached array, then inspect the native backbone chains.
The report is not a Design and cannot be applied, exported or simulated. Native
array indices are local to this capture, not proposed persistent residue IDs.
"""

from __future__ import annotations

from backend.core.mrdna_bridge import _build_nt_arrays
from backend.core.feature_identity import identity_factory


def staple_relocation_inventory(design, selected_keys, *, identity_seed):
    """Resolve the scaffold-stays/staple-relocates rule, without placing material.

    This inventory deliberately does not decide automatic triggering, partial
    domain splitting, lattice snapping or geometry. Output keys describe a
    proposed reclassification, not a persistent model or an executable command.
    """
    report = inspect_unpairing(design, selected_keys)
    residues = {r["index"]: r for run in report["affected_runs"]
                for r in run["residues"]}
    identifier = identity_factory(identity_seed)
    relocations = []
    for pair in report["removed_pairs"]:
        ends = [residues[index] for index in pair]
        by_role = {r["identity"]["strand_type"]: r for r in ends}
        if set(by_role) != {"scaffold", "staple"}:
            raise ValueError("Unpair relocation requires one scaffold and one staple")
        staple, scaffold = by_role["staple"], by_role["scaffold"]
        if staple["key"] is None or scaffold["key"] is None:
            raise ValueError("Unpair relocation requires native helix nucleotide keys")
        old_key = staple["key"]
        # Split provenance by source helix and strand, not by bp: a continuous
        # staple run retains a common destination and unchanged register/copy.
        helix_id = identifier("unpair-helix", [old_key[0], staple["identity"]["strand_id"]])
        relocations.append({
            "staple": staple,
            "scaffold": scaffold,
            "new_staple_key": (helix_id, *old_key[1:]),
        })
    return {"scope": "relocation inventory only; no lattice placement",
            "relocations": relocations, "affected_runs": report["affected_runs"]}


def inspect_unpairing(design, selected_keys):
    """Report affected ssDNA runs without changing identity, bonds or placement.

    Selection uses native (helix, bp, direction, copy) keys. Both endpoints lose
    pairing, but selection itself never expands to the former partner. Existing
    ssDNA contiguous with an affected run is included in that run, not selected.
    """
    if design.duplexes or design.overhang_bindings:
        raise ValueError("Explicit overhang pairing needs its own pairing inventory")
    if design.forced_ligations:
        raise ValueError("Forced ligations need a complete covalent-edge inventory")
    (
        positions, paired, _stack, three_prime, orientations, sequence,
        key_to_index, identities, chains,
    ) = _build_nt_arrays(design, return_nt_key=True, return_identity=True)
    keys = list(dict.fromkeys(tuple(key) for key in selected_keys))
    if not keys:
        raise ValueError("Select at least one native nucleotide")
    missing = [key for key in keys if key not in key_to_index]
    if missing:
        raise ValueError(f"Unresolved native nucleotide keys: {missing}")
    selected = {key_to_index[key] for key in keys}
    count = len(paired)
    flattened = [i for chain in chains for i in chain]
    if sorted(flattened) != list(range(count)):
        raise ValueError("Native chains do not partition the nucleotide inventory")
    for chain in chains:
        for offset, index in enumerate(chain):
            expected = chain[offset + 1] if offset + 1 < len(chain) else -1
            if int(three_prime[index]) != expected:
                raise ValueError("Backbone outside native linear chains is unsupported")
    for index, partner in enumerate(paired):
        if partner < -1 or partner >= count or partner == index:
            raise ValueError("Invalid native pairing inventory")
        if partner >= 0 and paired[partner] != index:
            raise ValueError("Asymmetric native pairing inventory")

    candidate = paired.copy()
    removed = set()
    for index in selected:
        partner = int(paired[index])
        if partner >= 0:
            removed.add(tuple(sorted((index, partner))))
            candidate[index] = candidate[partner] = -1
    affected = selected | {i for pair in removed for i in pair}
    index_to_key = {index: key for key, index in key_to_index.items()}

    def residue(index):
        return {
            "index": index,
            "key": index_to_key.get(index),
            "identity": dict(identities[index]),
            "base": sequence[index] if sequence is not None else None,
            "selected": index in selected,
        }

    runs = []
    for chain in chains:
        offset = 0
        while offset < len(chain):
            if candidate[chain[offset]] >= 0:
                offset += 1
                continue
            start = offset
            while offset < len(chain) and candidate[chain[offset]] < 0:
                offset += 1
            members = chain[start:offset]
            if not affected.intersection(members):
                continue
            anchors = []
            if start:
                anchors.append({"side": "5p", **residue(chain[start - 1])})
            if offset < len(chain):
                anchors.append({"side": "3p", **residue(chain[offset])})
            runs.append({
                "kind": ("free_strand", "overhang", "linker")[len(anchors)],
                "residues": [residue(i) for i in members],
                "anchors": anchors,
            })
    return {
        "scope": "detached native pair-edge experiment; no placement candidate",
        "selected": [residue(i) for i in sorted(selected)],
        "removed_pairs": sorted(removed),
        "affected_runs": runs,
        "native_nucleotide_count": count,
        "native_backbone_edge_count": int((three_prime >= 0).sum()),
        "native_frame_count": len(positions),
        "native_orientation_count": len(orientations),
    }
