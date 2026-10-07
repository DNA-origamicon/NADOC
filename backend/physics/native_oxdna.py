"""Explicit native chemical-landmark → calibrated oxDNA particle-frame boundary.

Native Full O5′ sites are not oxDNA centres of mass. The particle projection uses
the same transported helical site, with the existing physical phase convention;
it never estimates an axis from endpoints, infers provenance from a radius, or
changes native geometry. Authored untagged physical inputs remain physical.
"""

from __future__ import annotations

import math

import numpy as np

from backend.core.constants import BASE_DISPLACEMENT, HELIX_RADIUS
from backend.core.native_full_placement import SOURCE, NativePlacementError, positions_in_native_frame

PHYSICAL_SOURCE = "oxdna-particle-frame-v1"


def _physical_record(record):
    return {key: value for key, value in record.items()
            if key != "helical_site" and not key.startswith("slab_")}


def native_full_to_oxdna_geometry(design, geometry):
    """Return physical records; reject native records with missing or stale sites.

The source metadata is a contract, not a hint. A caller authoring an arbitrary
physical fold must first convert to physical records, then move those records.
An unknown named landmark cannot silently be written into a CM column.
"""
    out = []
    anchor_frames = {}
    native_extensions = set()
    for record in geometry:
        source = record.get("placement_source")
        if source in (None, PHYSICAL_SOURCE):
            if "helical_site" in record or any(key.startswith("slab_") for key in record):
                raise NativePlacementError("Physical input carries stale native placement metadata.")
            out.append(record)
            continue
        if source == "chemical-modification-v1":
            # Non-DNA labels have no row in the oxDNA nucleotide order.
            continue
        if source == "native-full-extension-v1":
            native_extensions.add((record["helix_id"], record["bp_index"], record["direction"]))
            out.append({**_physical_record(record), "placement_source": PHYSICAL_SOURCE})
            continue
        identity = (record.get("helix_id"), record.get("bp_index"), record.get("direction"), record.get("copy_k", 0))
        if source != SOURCE:
            raise NativePlacementError("No calibrated oxDNA conversion for this placement source.",
                                       details={"identity": identity, "source": source})
        try:
            site = record["helical_site"]
            origin = np.asarray(site["axis_point"], float)
            radial = np.asarray(site["radial_hat"], float)
            tangent = np.asarray(record["axis_tangent"], float)
            groove, roll, azimuth = (float(site[key]) for key in
                                     ("groove_offset_rad", "phase_roll_rad", "azimuth_rad"))
            reverse = record["direction"] == "REVERSE"
            if (record["direction"] not in ("FORWARD", "REVERSE")
                    or any(value.shape != (3,) for value in (origin, radial, tangent))
                    or not all(math.isfinite(value) for value in (groove, roll, azimuth))):
                raise ValueError("Malformed transported site")
            delta = groove if reverse else 0.0
            forward = math.cos(delta) * radial - math.sin(delta) * np.cross(tangent, radial)
            expected = positions_in_native_frame(origin, forward, tangent, np.asarray(reverse))
            for field, value in zip(("backbone_position", "base_position", "base_normal"), expected, strict=True):
                actual = np.asarray(record[field], float)
                if (actual.shape != (3,) or not np.all(np.isfinite(actual))
                        or not np.allclose(actual, value, rtol=0, atol=1e-8)):
                    raise NativePlacementError("Native Full coordinates disagree with their transported site.",
                        details={"identity": identity, "field": field,
                                 "expected": value.tolist(), "actual": actual.tolist()})
        except (KeyError, TypeError, ValueError) as error:
            if isinstance(error, NativePlacementError):
                raise
            raise NativePlacementError("Native Full needs complete transported-site metadata for oxDNA.",
                                       details={"identity": identity}) from error

        # Remove only the display's named phase convention. The geometric layer's
        # published radius/groove and the physical frame calibration stay unchanged.
        physical_radial = math.cos(roll) * radial - math.sin(roll) * np.cross(tangent, radial)
        physical_forward = math.cos(roll) * forward - math.sin(roll) * np.cross(tangent, forward)
        physical_reverse = (math.cos(groove) * physical_forward
                            + math.sin(groove) * np.cross(tangent, physical_forward))
        normal = physical_reverse - physical_forward
        length = float(np.linalg.norm(normal))
        if not math.isfinite(length) or length < 1e-9:
            raise NativePlacementError("Transported site has a degenerate physical groove.",
                                       details={"identity": identity, "groove_offset_rad": groove})
        normal /= length
        if reverse:
            normal = -normal
        position = origin + HELIX_RADIUS * physical_radial
        old_normal = np.asarray(record["base_normal"], float)
        old_z = tangent - np.dot(tangent, old_normal) * old_normal
        old_z /= np.linalg.norm(old_z)
        old_frame = np.column_stack([old_normal, np.cross(old_z, old_normal), old_z])
        physical_frame = np.column_stack([normal, np.cross(tangent, normal), tangent])
        anchor_frame = (np.asarray(record["backbone_position"], float),
                        position, physical_frame @ old_frame.T)
        anchor_frames[identity] = anchor_frame
        if identity[3] == 0:
            anchor_frames[identity[:3]] = anchor_frame
        out.append({**_physical_record(record), "placement_source": PHYSICAL_SOURCE,
                    "backbone_position": position.tolist(),
                    "base_position": (position + BASE_DISPLACEMENT * normal).tolist(),
                    "base_normal": normal.tolist()})

    # Carry a native extension's entire arc in its own anchor's local frame.
    # The native base-ring normal includes a real axial component; translating
    # alone would leave the old O5/normal convention in the physical tail and
    # change its anchor bond. The resolver then solves physical a1/a3 frames.
    if native_extensions:
        from backend.physics.oxdna_interface import extension_beads

        extension_frames = {key: anchor_frames[anchor] for key, anchor, _end in extension_beads(design)
                            if anchor in anchor_frames and key in native_extensions}
        missing = native_extensions - extension_frames.keys()
        if missing:
            raise NativePlacementError("Native extensions require their own native anchor frame for oxDNA conversion.",
                details={"unconverted_extensions": sorted(missing), "source": "native-full-extension-v1"})
        for record in out:
            key = (record["helix_id"], record["bp_index"], record["direction"])
            if key in extension_frames:
                old_origin, origin, rotation = extension_frames[key]
                for field in ("backbone_position", "base_position"):
                    if field in record:
                        record[field] = (origin + rotation @ (np.asarray(record[field], float)-old_origin)).tolist()
                for field in ("base_normal", "axis_tangent"):
                    if field in record:
                        record[field] = (rotation @ np.asarray(record[field], float)).tolist()
    return out
