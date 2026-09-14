"""Explicitly prescribed fixed-core streptavidin/DNA example geometry."""

import numpy as np
from backend.core.models import (
    Helix,
    Strand,
    Domain,
    Direction,
    Vec3,
    StrandType,
    BiotinDNA,
)
from backend.core.streptavidin import streptavidin_asset
import uuid
from scipy.spatial import cKDTree
from backend.core.constants import BDNA_RISE_PER_BP, NM_TO_OXDNA
from backend.core.geometry import nucleotide_positions_arrays


def pocket_geometry(particle, chain, tetramer_index=0):
    protein = particle.coating.protein
    template = streptavidin_asset("biotin_tether")
    a = np.array(
        [
            [x.x, x.y, x.z]
            for x in template.atoms
            if x.chain_id == "A" and x.name == "CA"
        ]
    )
    b = np.array(
        [
            [x.x, x.y, x.z]
            for x in protein.atoms
            if x.chain_id == chain and x.name == "CA"
        ]
    )
    u, _, vt = np.linalg.svd((a - a.mean(0)).T @ (b - b.mean(0)))
    r = vt.T @ u.T
    if np.linalg.det(r) < 0:
        vt[-1] *= -1
        r = vt.T @ u.T
    t = b.mean(0) - r @ a.mean(0)
    ligand = {
        x.name: np.array([x.x, x.y, x.z]) for x in template.atoms if x.res_name == "BTN"
    }
    anchor = r @ ligand["C11"] + t
    axis = r @ (ligand["C11"] - ligand["C10"])
    axis /= np.linalg.norm(axis)
    m = particle.pose.to_array() @ particle.coating.poses[tetramer_index].to_array()
    return m[:3, :3] @ anchor + m[:3, 3], m[:3, :3] @ axis


# Conservative native bead/segment clearance, in nm; geometric placement criteria,
# not calibrated binding energies or an equilibrium ssDNA conformation.
DNA_CLEARANCE = 0.5
DNA_DNA_CLEARANCE = 0.8
LINKER_CLEARANCE = 0.25


def _vec(a):
    return Vec3(x=float(a[0]), y=float(a[1]), z=float(a[2]))


def _segments(a, b, spacing=0.15):
    """Sample segments finely enough to screen between native beads as well."""
    a, b = np.atleast_2d(a), np.atleast_2d(b)
    count = max(2, int(np.ceil(np.max(np.linalg.norm(b - a, axis=1)) / spacing)) + 1)
    return (
        a[:, None, :] + np.linspace(0, 1, count)[None, :, None] * (b - a)[:, None, :]
    ).reshape(-1, 3)


def dna_clearance_points(helix):
    frames = nucleotide_positions_arrays(helix)
    backbone, bases = frames["positions"][::2], frames["base_positions"][::2]
    return np.vstack(
        [_segments(backbone[:-1], backbone[1:]), _segments(backbone, bases)]
    )


def extended_dna_seed(helix):
    """Simulation-only extended ssDNA seed, attached at the native 5′ bead."""
    frames = nucleotide_positions_arrays(helix)
    axis = frames["axis_tangents"][0]
    positions = (
        frames["positions"][0]
        + np.arange(helix.length_bp)[:, None] * axis * 0.7564 / NM_TO_OXDNA
    )
    return positions, frames["base_normals"][0], axis


def _directions(exit_axis, radial):
    normal = np.cross(exit_axis, radial)
    if np.linalg.norm(normal) < 1e-8:
        normal = np.cross(
            exit_axis, [1.0, 0.0, 0.0] if abs(exit_axis[0]) < 0.9 else [0.0, 1.0, 0.0]
        )
    normal /= np.linalg.norm(normal)
    tangent = np.cross(normal, exit_axis)
    yield exit_axis
    # A flexible linker permits the straight ideal helix to turn at its 5′ end.
    # Search rigid orientations/phases only: never distort rise, twist or bonds.
    for angle in np.deg2rad([30, 60, 85]):
        for phi in np.linspace(0, 2 * np.pi, 12, endpoint=False):
            yield np.cos(angle) * exit_axis + np.sin(angle) * (
                np.cos(phi) * tangent + np.sin(phi) * normal
            )


def build_dna_set(
    particle, sequence, chain="auto", linker_nm=2.0, dna_per_strep=1, design=None
):
    """Place exactly the requested occupancy on every already-applied tetramer.

    This finite deterministic search may reject a layout that a more extensive
    search could find. It never silently lowers occupancy or deforms native DNA.
    """
    if (
        particle.kind != "gold_nanosphere"
        or not particle.coating
        or not particle.coating.poses
    ):
        raise ValueError(
            "Apply a streptavidin coating to the gold sphere before attaching DNA."
        )
    if particle.biotin_dna:
        raise ValueError(
            "Remove the existing biotinylated DNA before creating another set."
        )
    sequence = sequence.strip().upper()
    if not 2 <= len(sequence) <= 200 or any(b not in "ACGT" for b in sequence):
        raise ValueError("Enter 2–200 DNA bases (A, C, G, T).")
    limit = 3 if particle.coating.mode == "biotin_tether" else 4
    if type(dna_per_strep) is not int or not 1 <= dna_per_strep <= limit:
        raise ValueError(
            f"Use 1–{limit} DNA per streptavidin for this coating; tethered pocket A is unavailable."
        )
    if chain not in ("auto", "A", "B", "C", "D") or (
        chain != "auto" and dna_per_strep != 1
    ):
        raise ValueError(
            "Use automatic pocket selection when attaching multiple DNA per streptavidin."
        )
    if not np.isfinite(linker_nm) or not 1 <= linker_nm <= 10:
        raise ValueError("Linker reach must be 1–10 nm.")
    particles = design.nanoparticles if design is not None else [particle]
    cores = [(p.pose.to_array()[:3, 3], p.diameter_nm / 2) for p in particles]
    clouds = []
    for p in particles:
        if not p.coating:
            continue
        xyz = np.array(
            [[a.x, a.y, a.z] for a in p.coating.protein.atoms if a.res_name != "BTN"]
        )
        for pose in p.coating.poses:
            m = p.pose.to_array() @ pose.to_array()
            clouds.append(xyz @ m[:3, :3].T + m[:3, 3])
    protein_tree = cKDTree(np.vstack(clouds))
    existing = []
    if design is not None:
        # Existing native DNA is an obstacle too; include only occupied strands.
        by_helix = {h.id: h for h in design.helices}
        for strand in design.strands:
            for domain in strand.domains:
                h = by_helix.get(domain.helix_id)
                if h is None:
                    continue
                frames = nucleotide_positions_arrays(h)
                indices = (frames["bp_indices"] >= domain.start_bp) & (
                    frames["bp_indices"] <= domain.end_bp
                )
                indices &= np.arange(len(indices)) % 2 == (
                    0 if domain.direction == Direction.FORWARD else 1
                )
                b, v = frames["positions"][indices], frames["base_positions"][indices]
                if len(b):
                    existing.append(_segments(b, v))
                    if len(b) > 1:
                        existing.append(_segments(b[:-1], b[1:]))
    existing_tree = cKDTree(np.vstack(existing)) if existing else None

    def clear(points, margin, dna_tree=None):
        if any(
            np.min(np.linalg.norm(points - c, axis=1)) < r + margin for c, r in cores
        ):
            return False
        if np.min(protein_tree.query(points)[0]) < margin:
            return False
        for tree in (existing_tree, dna_tree):
            if tree is not None and np.min(tree.query(points)[0]) < DNA_DNA_CLEARANCE:
                return False
        return True

    selected = []
    accepted_clouds = []
    center = particle.pose.to_array()[:3, 3]
    for index in range(len(particle.coating.poses)):
        candidates = []
        for site in "ABCD":
            if particle.coating.mode == "biotin_tether" and site == "A":
                continue
            if chain != "auto" and chain != site:
                continue
            anchor, exit_axis = pocket_geometry(particle, site, index)
            radial = (anchor - center) / np.linalg.norm(anchor - center)
            candidates.append(
                (float(exit_axis @ radial), site, anchor, exit_axis, radial)
            )
        candidates.sort(key=lambda item: item[0], reverse=True)
        count = 0
        for _, site, anchor, exit_axis, radial in candidates:
            dna_tree = cKDTree(np.vstack(accepted_clouds)) if accepted_clouds else None
            endpoint = anchor + linker_nm * exit_axis
            linker = _segments(anchor, endpoint)
            if not clear(linker, LINKER_CLEARANCE, dna_tree):
                continue
            chosen = None
            for axis in _directions(exit_axis, radial):
                if axis @ radial < -0.05:
                    continue
                for phase in np.linspace(0, 2 * np.pi, 8, endpoint=False):
                    h = Helix(
                        axis_start=_vec(np.zeros(3)),
                        axis_end=_vec(axis * (len(sequence) - 1) * BDNA_RISE_PER_BP),
                        length_bp=len(sequence),
                        phase_offset=float(phase),
                        label="Biotinylated DNA",
                    )
                    first = nucleotide_positions_arrays(h)["positions"][0]
                    h.axis_start = _vec(endpoint - first)
                    h.axis_end = _vec(
                        endpoint - first + axis * (len(sequence) - 1) * BDNA_RISE_PER_BP
                    )
                    points = dna_clearance_points(h)
                    seed, _, _ = extended_dna_seed(h)
                    seed_points = _segments(seed[:-1], seed[1:])
                    if clear(points, DNA_CLEARANCE, dna_tree) and clear(
                        seed_points, DNA_CLEARANCE, dna_tree
                    ):
                        chosen = h, np.vstack([points, seed_points])
                        break
                if chosen is not None:
                    break
            if chosen is None:
                continue
            h, points = chosen
            h.id = "__strep_dna__" + uuid.uuid4().hex
            s = Strand(
                domains=[
                    Domain(
                        helix_id=h.id,
                        start_bp=0,
                        end_bp=len(sequence) - 1,
                        direction=Direction.FORWARD,
                    )
                ],
                strand_type=StrandType.STAPLE,
                sequence=sequence,
                name=f"5′ biotin–DNA · strep {index + 1} pocket {site}",
            )
            record = BiotinDNA(
                strand_id=s.id,
                helix_id=h.id,
                tetramer_index=index,
                placement_version=2,
                chain=site,
                linker_nm=linker_nm,
            )
            selected.append((record, h, s))
            accepted_clouds.append(np.vstack([points, linker]))
            count += 1
            if count == dna_per_strep:
                break
        if count != dna_per_strep:
            raise ValueError(
                f"Could not place {dna_per_strep} DNA on streptavidin {index + 1} without clashes (found {count}). Nothing was attached. Try fewer DNA, a longer linker, or lower coating coverage."
            )
    return selected


def build_dna(particle, sequence, chain="auto", linker_nm=2.0):
    """Compatibility helper for the original single-tetramer example."""
    if not particle.coating or len(particle.coating.poses) != 1:
        raise ValueError(
            "This helper requires exactly one applied streptavidin tetramer."
        )
    return build_dna_set(particle, sequence, chain, linker_nm)[0]


def validate_fixed_core_design(design):
    for p in design.nanoparticles:
        if (
            not p.oxdna_fixed_core
            or p.kind != "gold_nanosphere"
            or not p.coating
            or not p.coating.poses
            or not p.biotin_dna
        ):
            raise ValueError(
                "oxDNA gold support requires a fixed gold core with applied streptavidin and biotinylated DNA. Configure this in Conjugate Manager."
            )
        occupied = set()
        for record in p.biotin_dna:
            if record.tetramer_index >= len(p.coating.poses):
                raise ValueError(
                    "The biotin–DNA attachment references a missing streptavidin tetramer."
                )
            key = (record.tetramer_index, record.chain)
            if key in occupied:
                raise ValueError(
                    "Two DNA strands cannot occupy the same streptavidin pocket."
                )
            occupied.add(key)
            strand = next((s for s in design.strands if s.id == record.strand_id), None)
            helix = next((h for h in design.helices if h.id == record.helix_id), None)
            if strand is None or helix is None:
                raise ValueError(
                    "The nanoparticle biotin–DNA attachment references a missing strand or helix."
                )
            if (
                len(strand.domains) != 1
                or strand.domains[0].helix_id != helix.id
                or strand.domains[0].start_bp != 0
                or strand.domains[0].end_bp != helix.length_bp - 1
                or strand.domains[0].direction != Direction.FORWARD
            ):
                raise ValueError(
                    "The biotinylated DNA handle must remain a complete forward strand on its owned helix."
                )
            if p.coating.mode == "biotin_tether" and record.chain == "A":
                raise ValueError(
                    "Streptavidin pocket A is already occupied by the gold tether."
                )
            if (
                np.linalg.norm(helix.axis_end.to_array() - helix.axis_start.to_array())
                < 1e-8
            ):
                raise ValueError("The biotinylated DNA handle requires a nonzero axis.")
