"""Portable Watson-Crick trajectory evaluator for bare Alpine compute nodes.

Alpine's system ``python3`` has no NumPy, SciPy, or MDAnalysis.  The application
therefore builds a compact atom-pair plan locally, where those dependencies already
exist, and stages the JSON plan beside this script.  On the compute node this module
reads only the last plateau window from the NAMD DCD and writes the same
``ref_relative_paired_fraction`` series used by ``md_health.wc_frame_metrics``.

The node path is deliberately Python-3.6-compatible and standard-library-only.
Local-only helpers at the bottom import MDAnalysis-backed NADOC code lazily when the
plan is built before upload.
"""

# No ``from __future__ import annotations``: Alpine's bare node Python is < 3.7.
import argparse
import array
import json
import os
import struct
import sys
from pathlib import Path


PLAN_VERSION = 1
DEFAULT_WINDOW = 10
DEFAULT_REF_DELTA_ANG = 0.75


class UnsupportedDCD(Exception):
    pass


def _read_layout(path):
    """Return the fixed-record NAMD DCD layout using only header reads."""
    size = os.path.getsize(path)
    with open(path, "rb") as fh:
        marker = fh.read(4)
        if len(marker) != 4:
            raise UnsupportedDCD("file too small for a DCD header")
        if struct.unpack("<i", marker)[0] == 84:
            endian = "<"
        elif struct.unpack(">i", marker)[0] == 84:
            endian = ">"
        else:
            raise UnsupportedDCD("bad leading DCD record marker")
        if fh.read(4) != b"CORD":
            raise UnsupportedDCD("bad DCD magic")
        raw = fh.read(80)
        if len(raw) != 80:
            raise UnsupportedDCD("truncated DCD control block")
        icntrl = struct.unpack(endian + "20i", raw)
        if struct.unpack(endian + "i", fh.read(4))[0] != 84:
            raise UnsupportedDCD("bad trailing DCD control marker")
        if icntrl[8] != 0:
            raise UnsupportedDCD("fixed-atom DCDs are not supported")
        if icntrl[11]:
            raise UnsupportedDCD("4D DCDs are not supported")
        has_cell = bool(icntrl[10]) and icntrl[19] > 0

        title_bytes = struct.unpack(endian + "i", fh.read(4))[0]
        fh.seek(title_bytes, 1)
        if struct.unpack(endian + "i", fh.read(4))[0] != title_bytes:
            raise UnsupportedDCD("bad DCD title record")
        if struct.unpack(endian + "i", fh.read(4))[0] != 4:
            raise UnsupportedDCD("bad DCD atom-count record")
        n_atoms = struct.unpack(endian + "i", fh.read(4))[0]
        if struct.unpack(endian + "i", fh.read(4))[0] != 4 or n_atoms <= 0:
            raise UnsupportedDCD("invalid DCD atom count")
        header_bytes = fh.tell()

    cell_bytes = 56 if has_cell else 0
    axis_bytes = 8 + 4 * n_atoms
    frame_bytes = cell_bytes + 3 * axis_bytes
    n_frames = max(0, (size - header_bytes) // frame_bytes)
    return {
        "endian": endian,
        "n_atoms": n_atoms,
        "has_cell": has_cell,
        "header_bytes": header_bytes,
        "frame_bytes": frame_bytes,
        "n_frames": int(n_frames),
    }


def _read_axis(fh, endian, n_atoms, selected):
    marker = fh.read(4)
    if len(marker) != 4 or struct.unpack(endian + "i", marker)[0] != 4 * n_atoms:
        raise UnsupportedDCD("bad coordinate-block marker")
    raw = fh.read(4 * n_atoms)
    if len(raw) != 4 * n_atoms:
        raise UnsupportedDCD("torn coordinate block")
    if struct.unpack(endian + "i", fh.read(4))[0] != 4 * n_atoms:
        raise UnsupportedDCD("bad trailing coordinate marker")
    values = array.array("f")
    values.frombytes(raw)
    native_little = sys.byteorder == "little"
    file_little = endian == "<"
    if native_little != file_little:
        values.byteswap()
    return [float(values[i]) for i in selected]


def _read_selected_frame(fh, layout, frame_index, selected):
    fh.seek(layout["header_bytes"] + frame_index * layout["frame_bytes"])
    lengths = None
    if layout["has_cell"]:
        if struct.unpack(layout["endian"] + "i", fh.read(4))[0] != 48:
            raise UnsupportedDCD("bad unit-cell record marker")
        cell = struct.unpack(layout["endian"] + "6d", fh.read(48))
        if struct.unpack(layout["endian"] + "i", fh.read(4))[0] != 48:
            raise UnsupportedDCD("bad trailing unit-cell marker")
        # NAMD/CHARMM order: A, cos(gamma), B, cos(beta), cos(alpha), C.
        candidate = (abs(cell[0]), abs(cell[2]), abs(cell[5]))
        if min(candidate) > 0:
            lengths = candidate
    axes = [
        _read_axis(fh, layout["endian"], layout["n_atoms"], selected)
        for _ in range(3)
    ]
    return dict(
        (atom_index, (axes[0][i], axes[1][i], axes[2][i]))
        for i, atom_index in enumerate(selected)
    ), lengths


def _minimum_image(delta, length):
    if not length:
        return delta
    # Python and NumPy both use ties-to-even rounding; exact half-cell ties do not
    # affect a 3.6-A hydrogen-bond cutoff in these much larger solvent boxes.
    return delta - length * round(delta / length)


def wc_series(dcd_path, plan, window=DEFAULT_WINDOW):
    """Return trailing WC reference-relative fractions from a NAMD DCD."""
    if int(plan.get("version", 0)) != PLAN_VERSION:
        raise ValueError("unsupported WC-plan version")
    pairs = plan.get("pairs") or []
    if not pairs:
        raise ValueError("WC plan contains no pairs")
    layout = _read_layout(dcd_path)
    expected_atoms = int(plan.get("n_atoms") or 0)
    if expected_atoms and expected_atoms != layout["n_atoms"]:
        raise ValueError(
            "WC plan/DCD atom-count mismatch: %d != %d"
            % (expected_atoms, layout["n_atoms"])
        )
    if layout["n_frames"] <= 0:
        return []

    selected = sorted(
        set(
            int(index)
            for pair in pairs
            for atom_pair in pair["atom_pairs"]
            for index in atom_pair
        )
    )
    if not selected or selected[-1] >= layout["n_atoms"]:
        raise ValueError("WC plan contains an out-of-range atom index")
    ref_delta = float(plan.get("ref_delta_ang", DEFAULT_REF_DELTA_ANG))
    start = max(0, layout["n_frames"] - max(1, int(window)))
    out = []
    with open(dcd_path, "rb") as fh:
        for frame_index in range(start, layout["n_frames"]):
            coords, lengths = _read_selected_frame(fh, layout, frame_index, selected)
            good = 0
            for pair in pairs:
                intact = True
                for atom_pair, reference in zip(
                    pair["atom_pairs"], pair["ref_distances"]
                ):
                    a = coords[int(atom_pair[0])]
                    b = coords[int(atom_pair[1])]
                    dx, dy, dz = a[0] - b[0], a[1] - b[1], a[2] - b[2]
                    if lengths is not None:
                        dx = _minimum_image(dx, lengths[0])
                        dy = _minimum_image(dy, lengths[1])
                        dz = _minimum_image(dz, lengths[2])
                    limit = float(reference) + ref_delta
                    if dx * dx + dy * dy + dz * dz > limit * limit:
                        intact = False
                        break
                if intact:
                    good += 1
            out.append(round(float(good) / len(pairs), 4))
    return out


def _source_fingerprint(package_dir, stem):
    package_dir = Path(package_dir)
    paths = [package_dir / (stem + ".psf"), package_dir / (stem + ".pdb")]
    sidecar = package_dir / (stem + "_ss_exclusion.json")
    if sidecar.exists():
        paths.append(sidecar)
    return {
        p.name: {"size": p.stat().st_size, "mtime_ns": p.stat().st_mtime_ns}
        for p in paths
    }


def _normal_resid(value):
    try:
        return str(int(value))
    except (TypeError, ValueError):
        return str(value).strip()


def _read_topology_atoms(psf, wanted_names):
    """Read only WC-relevant PSF atoms; avoid a multi-million-Atom Universe."""
    atoms = {}
    residues = {}
    n_atoms = None
    with open(psf, errors="replace") as fh:
        for line in fh:
            if "!NATOM" not in line:
                continue
            n_atoms = int(line.split()[0])
            for _ in range(n_atoms):
                fields = next(fh).split()
                if len(fields) < 6:
                    raise ValueError("malformed PSF NATOM row")
                index = int(fields[0]) - 1
                segid, resid, resname, atomname = (
                    fields[1],
                    _normal_resid(fields[2]),
                    fields[3],
                    fields[4],
                )
                key = (segid, resid)
                residue = residues.setdefault(
                    key,
                    {"segid": segid, "resid": resid, "resname": resname, "atoms": {}},
                )
                if atomname in wanted_names:
                    atoms[index] = (key, atomname)
                    residue["atoms"][atomname] = index
            break
    if n_atoms is None:
        raise ValueError("PSF has no !NATOM section")
    return n_atoms, atoms, residues


def _read_selected_pdb_positions(pdb, selected_indices):
    """Coordinates by zero-based PSF/PDB atom ordinal for selected atoms only."""
    wanted = set(selected_indices)
    positions = {}
    ordinal = 0
    with open(pdb, errors="replace") as fh:
        for line in fh:
            if not line.startswith(("ATOM  ", "HETATM")):
                continue
            if ordinal in wanted:
                try:
                    xyz = (
                        float(line[30:38]),
                        float(line[38:46]),
                        float(line[46:54]),
                    )
                except ValueError:
                    fields = line.split()
                    xyz = tuple(float(x) for x in fields[6:9])
                positions[ordinal] = xyz
            ordinal += 1
    missing = wanted - set(positions)
    if missing:
        raise ValueError("PDB is missing %d WC-relevant atom(s)" % len(missing))
    return positions


def _topology_exclusions(package_dir, stem):
    path = Path(package_dir) / (stem + "_ss_exclusion.json")
    try:
        data = json.loads(path.read_text())
        return set(tuple(str(v) for v in row) for row in data.get("topology_last_char", []))
    except (OSError, ValueError, TypeError):
        return set()


def build_plan(package_dir, stem):
    """Build the canonical pair plan locally without loading every solvent atom.

    The old implementation delegated this to an MDAnalysis Universe.  That was
    scientifically correct but peaked at 1.8 GB for 24hb_2xT during submission.
    PSF/PDB ordering is the DCD ordering, so a streaming topology read plus the few
    base atoms needed by the WC metric produces the identical plan at a tiny fraction
    of the memory cost.
    """
    import numpy as np  # local-only lazy imports
    from scipy.spatial import cKDTree
    from backend.core.md_health import (
        C1_SEARCH_HI,
        C1_SEARCH_LO,
        WC_ATOMS,
        _C1_NO_PARTNER_ANG,
    )

    package_dir = Path(package_dir)
    psf = package_dir / (stem + ".psf")
    pdb = package_dir / (stem + ".pdb")
    wanted = {"C1'", "C1X"}
    for atom_names in WC_ATOMS.values():
        for a, b in atom_names:
            wanted.add(a)
            wanted.add(b)
    n_atoms, selected_atoms, residues = _read_topology_atoms(psf, wanted)
    positions = _read_selected_pdb_positions(pdb, selected_atoms)

    c1_rows = []
    for key, residue in residues.items():
        index = residue["atoms"].get("C1'")
        if index is None:
            index = residue["atoms"].get("C1X")
        if index is not None:
            c1_rows.append((index, key, residue))
    c1_rows.sort(key=lambda row: row[0])
    if not c1_rows:
        raise RuntimeError("no C1' atoms found for Alpine early-stop")
    c1_pos = np.asarray([positions[row[0]] for row in c1_rows], dtype=float)
    tree = cKDTree(c1_pos)

    # Exact union used by md_health._unpaired_exclusion_set: topology sidecar plus
    # geometric native-ssDNA detection.
    exclusions = _topology_exclusions(package_dir, stem)
    for i, (_, key, _) in enumerate(c1_rows):
        neighbours = [
            j
            for j in tree.query_ball_point(c1_pos[i], 11.0)
            if j != i and c1_rows[j][1][0] != key[0]
        ]
        closest = min(
            (float(np.linalg.norm(c1_pos[i] - c1_pos[j])) for j in neighbours),
            default=99.0,
        )
        if closest > _C1_NO_PARTNER_ANG:
            exclusions.add((key[0][-1], key[1]))

    candidates = []
    for i, j in tree.query_pairs(C1_SEARCH_HI):
        _, key_i, _ = c1_rows[i]
        _, key_j, _ = c1_rows[j]
        if key_i[0] == key_j[0]:
            continue
        if (key_i[0][-1], key_i[1]) in exclusions:
            continue
        if (key_j[0][-1], key_j[1]) in exclusions:
            continue
        distance = float(np.linalg.norm(c1_pos[i] - c1_pos[j]))
        if distance >= C1_SEARCH_LO:
            candidates.append((distance, i, j))
    candidates.sort()

    used = set()
    pairs = []
    for _, i, j in candidates:
        if i in used or j in used:
            continue
        _, key_i, res_i = c1_rows[i]
        _, key_j, res_j = c1_rows[j]
        atom_pairs = []
        ref_distances = []
        for name_i, name_j in WC_ATOMS.get(
            (res_i["resname"].strip(), res_j["resname"].strip()), []
        ):
            index_i = res_i["atoms"].get(name_i)
            index_j = res_j["atoms"].get(name_j)
            if index_i is None or index_j is None:
                continue
            atom_pairs.append([index_i, index_j])
            ref_distances.append(
                float(
                    np.linalg.norm(
                        np.asarray(positions[index_i]) - np.asarray(positions[index_j])
                    )
                )
            )
        if atom_pairs:
            used.add(i)
            used.add(j)
            pairs.append(
                {
                    "res_a": "%s:%s%s" % (key_i[0], res_i["resname"], key_i[1]),
                    "res_b": "%s:%s%s" % (key_j[0], res_j["resname"], key_j[1]),
                    "atom_pairs": atom_pairs,
                    "ref_distances": ref_distances,
                }
            )
    if not pairs:
        raise RuntimeError("no Watson-Crick pairs found for Alpine early-stop")
    return {
        "version": PLAN_VERSION,
        "metric": "wc_ref_relative_paired_fraction",
        "n_atoms": int(n_atoms),
        "ref_delta_ang": DEFAULT_REF_DELTA_ANG,
        "source": _source_fingerprint(package_dir, stem),
        "pairs": pairs,
    }


def ensure_plan(package_dir, stem, filename="nadoc_wc_plan.json"):
    """Return a fresh/cached plan path for an immutable prepared package."""
    package_dir = Path(package_dir)
    path = package_dir / filename
    fingerprint = _source_fingerprint(package_dir, stem)
    try:
        cached = json.loads(path.read_text())
        if (
            cached.get("version") == PLAN_VERSION
            and cached.get("source") == fingerprint
            and cached.get("pairs")
        ):
            return path
    except (OSError, ValueError, TypeError):
        pass
    plan = build_plan(package_dir, stem)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(plan, separators=(",", ":")))
    os.replace(str(tmp), str(path))
    return path


def main(argv=None):
    ap = argparse.ArgumentParser(description="portable NADOC WC DCD evaluator")
    ap.add_argument("--dcd", required=True)
    ap.add_argument("--plan", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--window", type=int, default=DEFAULT_WINDOW)
    args = ap.parse_args(argv)
    try:
        try:
            os.unlink(args.out)
        except OSError:
            pass
        with open(args.plan) as fh:
            plan = json.load(fh)
        series = wc_series(args.dcd, plan, window=args.window)
        if not series:
            raise ValueError("DCD has no complete frames")
        with open(args.out, "w") as fh:
            json.dump(series, fh)
        print(
            "[nadoc-wc] wrote %d trailing WC frames -> %s" % (len(series), args.out),
            file=sys.stderr,
        )
        return 0
    except Exception as exc:
        print("[nadoc-wc] %s: %s" % (type(exc).__name__, exc), file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
