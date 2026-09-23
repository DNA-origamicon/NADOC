"""Strict source checks for lattice interchange, before document replacement."""


def validate_cadnano_source(data):
    helices = data.get("vstrands", [])
    by_num = {h["num"]: h for h in helices}
    if len(by_num) != len(helices):
        raise ValueError("Duplicate caDNAno helix numbers.")
    widths = {len(h["scaf"]) for h in helices}
    if len(widths) != 1:
        raise ValueError("caDNAno helix arrays must have a common width.")
    for h in helices:
        n = len(h["scaf"])
        if len(h["stap"]) != n:
            raise ValueError("caDNAno scaffold and staple array lengths differ.")
        for key in ("scaf", "stap"):
            for bp, entry in enumerate(h[key]):
                if len(entry) != 4 or any(type(x) is not int for x in entry):
                    raise ValueError(
                        f"Invalid {key} pointer at helix {h['num']}, bp {bp}."
                    )
                for offset, reverse in ((0, 2), (2, 0)):
                    target, pos = entry[offset : offset + 2]
                    if (target, pos) == (-1, -1):
                        continue
                    if target not in by_num or not 0 <= pos < len(by_num[target][key]):
                        raise ValueError(
                            f"Missing or out-of-range {key} link target ({target}, {pos})."
                        )
                    back = by_num[target][key][pos][reverse : reverse + 2]
                    if list(back) != [h["num"], bp]:
                        raise ValueError(
                            f"Nonreciprocal {key} link at helix {h['num']}, bp {bp}."
                        )
        for bp in range(n):
            loop = h.get("loop", [])[bp] if bp < len(h.get("loop", [])) else 0
            skip = h.get("skip", [])[bp] if bp < len(h.get("skip", [])) else 0
            if (
                type(loop) is not int
                or loop < 0
                or skip not in (0, -1)
                or (loop and skip)
            ):
                raise ValueError(
                    f"Conflicting/invalid loop and skip at helix {h['num']}, bp {bp}."
                )


def validate_scadnano_source(data):
    grid = data.get("grid", "square")
    if grid not in ("square", "honeycomb"):
        raise ValueError(
            f"Unsupported scadnano grid {grid!r}; use square or honeycomb."
        )
    if data.get("groups"):
        raise ValueError(
            "scadnano helix groups/transforms are not supported by this importer."
        )
    helices = data.get("helices", [])
    indices = [h.get("idx", i) for i, h in enumerate(helices)]
    if len(set(indices)) != len(indices):
        raise ValueError("Duplicate scadnano helix indices.")
    for h in helices:
        if any(h.get(k) for k in ("position", "roll", "pitch", "yaw", "group")):
            raise ValueError(
                "scadnano helix positions/rotations/groups are unsupported by this lattice importer."
            )
    domains = []
    for si, strand in enumerate(data.get("strands", [])):
        if strand.get("circular") and not strand.get("is_scaffold"):
            raise ValueError(
                f"Strand {si}: circular non-scaffold backbones are unsupported; import would delete a molecule."
            )
        for field in (
            "5prime_modification",
            "3prime_modification",
            "internal_modifications",
            "modification_5p",
            "modification_3p",
            "modifications_int",
        ):
            if strand.get(field):
                raise ValueError(f"Strand {si}: unsupported scadnano {field}.")
        parts = strand.get("domains", [])
        if not any("helix" in d for d in parts):
            raise ValueError(f"Strand {si} contains no supported helix domains.")
        length = 0
        for di, d in enumerate(parts):
            if "loopout" in d:
                if (
                    type(d["loopout"]) is not int
                    or d["loopout"] <= 0
                    or di == 0
                    or di == len(parts) - 1
                    or "helix" not in parts[di - 1]
                    or "helix" not in parts[di + 1]
                ):
                    raise ValueError(
                        f"Strand {si}: loopout must join two helix domains and have positive length."
                    )
                length += d["loopout"]
                continue
            if "extension_num_bases" in d:
                if (
                    di not in (0, len(parts) - 1)
                    or type(d["extension_num_bases"]) is not int
                    or d["extension_num_bases"] <= 0
                ):
                    raise ValueError(f"Strand {si}: invalid/internal extension.")
                length += d["extension_num_bases"]
                continue
            if d["helix"] not in indices:
                raise ValueError(f"Strand {si}: unknown helix {d['helix']}.")
            if (
                type(d["forward"]) is not bool
                or type(d["start"]) is not int
                or type(d["end"]) is not int
                or d["start"] >= d["end"]
            ):
                raise ValueError(
                    f"Strand {si}: empty/reversed or malformed domain bounds."
                )
            if any(
                type(count) is not int or count <= 0
                for _, count in d.get("insertions", [])
            ):
                raise ValueError(
                    f"Strand {si}: insertion counts must be positive integers."
                )
            mods = {}
            for bp, count in [(bp, -1) for bp in d.get("deletions", [])] + d.get(
                "insertions", []
            ):
                if (
                    type(bp) is not int
                    or not d["start"] <= bp < d["end"]
                    or type(count) is not int
                    or count == 0
                    or count < -1
                    or bp in mods
                ):
                    raise ValueError(
                        f"Strand {si}: conflicting/invalid insertion or deletion at {bp}."
                    )
                mods[bp] = count
            domains.append((d, mods))
            length += d["end"] - d["start"] + sum(mods.values())
        if strand.get("sequence") is not None and len(strand["sequence"]) != length:
            raise ValueError(
                f"Strand {si}: sequence length does not match domains, insertions and extensions ({length})."
            )
    # A missing modification on the opposite domain means zero, not permission
    # to symmetrize a source design whose two sides have different chemistry.
    declared = {}
    for d, mods in domains:
        for bp, count in mods.items():
            key = (d["helix"], bp)
            if key in declared and declared[key] != count:
                raise ValueError(f"Conflicting scadnano insertion/deletion at {key}.")
            declared[key] = count
    for d, mods in domains:
        for (hid, bp), count in declared.items():
            if (
                d["helix"] == hid
                and d["start"] <= bp < d["end"]
                and mods.get(bp, 0) != count
            ):
                raise ValueError(
                    f"Asymmetric scadnano insertion/deletion at helix {hid}, bp {bp}; NADOC uses helix-level modifications."
                )


def require_import_integrity(design):
    from backend.core.topology_integrity import (
        domain_order_errors,
        occupancy_errors,
        junction_errors,
    )
    from backend.core.sequences import strand_sequence_length

    errors = (
        domain_order_errors(design) + occupancy_errors(design) + junction_errors(design)
    )
    if len({h.id for h in design.helices}) != len(design.helices):
        errors.append("Duplicate helix IDs.")
    if len({s.id for s in design.strands}) != len(design.strands):
        errors.append("Duplicate strand IDs.")
    for s in design.strands:
        if s.sequence is not None and len(s.sequence) != strand_sequence_length(
            design, s
        ):
            errors.append(f"Strand {s.id}: inconsistent sequence length.")
    if errors:
        raise ValueError("Invalid imported topology: " + "; ".join(errors[:8]))


def add_same_helix_junctions(strands, ligations):
    """Keep discontinuous same-helix paths as explicit directed connections."""
    from backend.core.models import ForcedLigation, Direction

    result = list(ligations)
    for s in strands:
        for a, b in zip(s.domains, s.domains[1:]):
            step = 1 if a.direction == Direction.FORWARD else -1
            if a.helix_id == b.helix_id and (
                a.direction != b.direction or b.start_bp != a.end_bp + step
            ):
                result.append(
                    ForcedLigation(
                        three_prime_helix_id=a.helix_id,
                        three_prime_bp=a.end_bp,
                        three_prime_direction=a.direction,
                        five_prime_helix_id=b.helix_id,
                        five_prime_bp=b.start_bp,
                        five_prime_direction=b.direction,
                    )
                )
    return result
