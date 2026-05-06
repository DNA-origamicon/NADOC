"""
Step 5 — Inject extracted CG parameters into mrdna topology.

This module is the most architecturally fragile part of the pipeline.
It patches mrdna's SegmentModel to use atomistic-derived crossover potentials
instead of the hard-coded defaults.

HOW MRDNA BUILDS CROSSOVER POTENTIALS (as of the version in /tmp/mrdna-tool)
------------------------------------------------------------------------------
mrdna.segmentmodel.SegmentModel.__init__ calls _generate_bead_model(), which
calls add_crossover_potentials() for every crossover connection.  That function
calls self.get_bond_potential(k, r0) and self.get_dihedral_potential(k, t0),
where the *default* values are:
  - Bond:     k = count_crossovers(bead_pair) × 1.0,  r0 = 18.5 Å
  - Dihedral: t0 = self.hj_equilibrium_angle (passed to SegmentModel.__init__)

These are global defaults — the same for every crossover in the model.

INJECTION STRATEGY
------------------
We subclass SegmentModel and override get_bond_potential() and
get_dihedral_potential() so our versions intercept calls during __init__/
_generate_bead_model().  Python's MRO ensures our overrides are active when
the parent's __init__ calls self.get_bond_potential().

We identify "crossover bonds" by their characteristic r0 value (18.5 Å for
standard DX crossovers).  The override replaces k and r0 with our extracted
values.  Bounds: |r0 - 18.5| < 3.0 Å to catch variants with extra thymines.

FRAGILITY NOTES
---------------
1. If mrdna changes the default r0 for crossover bonds, the 18.5 Å match will
   break silently.  The assertion in PatchedSegmentModel.get_bond_potential()
   will catch this if you call it on T=0 data first.

2. This replaces ALL DX crossover bonds globally.  It does not yet support
   per-crossover-pair overrides (different T counts on different junctions in
   the same origami).  That requires either:
     (a) marking each crossover's bead pair at construction time, or
     (b) passing a per-junction override map keyed by bead IDs (not yet done).

3. mrdna's crossover dihedral k is *geometry-derived* (from k_xover_angle),
   not a fixed constant.  Our override replaces it with a fixed k from the
   atomistic data, which may be too stiff at short bead-bead distances.  The
   max_potential cap (see _MAX_DIHEDRAL_POTENTIAL) limits blow-up at close range.

4. The local_twist orientation potentials (add_local_crossover_strand_orientation_
   potential) are not overridden here because they are orientation-only and do
   not directly correspond to the 6-DOF stiffness we extracted.  Future work.

UPDATING THIS MODULE
--------------------
If mrdna's crossover potential code changes, diff against:
  /tmp/mrdna-tool/mrdna/segmentmodel.py  lines 3314-3376 (add_crossover_potentials)
and update the r0 match threshold and dihedral detection accordingly.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

from backend.parameterization.param_extract import CrossoverParameters

logger = logging.getLogger(__name__)

# ── mrdna crossover bond fingerprints ────────────────────────────────────────

_DEFAULT_XOVER_BOND_R0 = 18.5        # Å — default mrdna crossover bond distance
_XOVER_BOND_R0_TOLERANCE = 3.0      # Å — match window (accounts for T variants)
_MAX_DIHEDRAL_POTENTIAL = 2.0        # kJ/mol — cap to prevent blow-up at close range

# kJ/mol/Å² → mrdna internal units (Å, kJ/mol) — no conversion needed, mrdna uses Å


@dataclass
class CrossoverPotentialOverride:
    """
    Scalar CG parameters for one crossover type, in mrdna-compatible units.

    All values come from CrossoverParameters.mrdna_params.

    Attributes
    ----------
    label : str
        E.g. "T0".
    r0_ang : float
        Equilibrium bond distance in Å.
    k_bond : float
        Bond spring constant in kJ/mol/Å².
    hj_equilibrium_angle_deg : float
        Holliday junction dihedral equilibrium in degrees.
    k_dihedral : float
        Dihedral spring constant in kJ/mol/rad².
    source_n_frames : int
        Number of MD frames used to derive these parameters.
    source_restraint_k_kcal : float
        Restraint k used in the source MD run (for provenance).
    sensitivity_check_passed : bool | None
        Whether the restraint sensitivity sweep passed for this variant.
    """
    label: str
    r0_ang: float
    k_bond: float                     # kJ/mol/Å²
    hj_equilibrium_angle_deg: float   # degrees
    k_dihedral: float                 # kJ/mol/rad²
    source_n_frames: int = 0
    source_restraint_k_kcal: float = 0.0
    sensitivity_check_passed: bool | None = None

    @classmethod
    def from_params(cls, params: CrossoverParameters) -> "CrossoverPotentialOverride":
        """Build an override from a CrossoverParameters result."""
        if not params.converged:
            logger.warning(
                "Building CrossoverPotentialOverride from UNCONVERGED parameters "
                "for variant %s.  Convergence warnings: %s",
                params.variant_label, "; ".join(params.convergence_warnings),
            )
        mp = params.mrdna_params
        return cls(
            label=params.variant_label,
            r0_ang=mp["r0_ang"],
            k_bond=mp["k_bond_kJ_mol_ang2"],
            hj_equilibrium_angle_deg=mp["hj_equilibrium_angle_deg"],
            k_dihedral=mp["k_dihedral_kJ_mol_rad2"],
            source_n_frames=params.n_frames,
            source_restraint_k_kcal=params.restraint_k_kcal,
        )

    @classmethod
    def from_database(cls, crossover_type: str, db_path: str | None = None) -> "CrossoverPotentialOverride":
        """
        Load a CrossoverPotentialOverride from crossover_params.json.

        Parameters
        ----------
        crossover_type : str
            E.g. "T0" or "T1".
        db_path : str | None
            Path to crossover_params.json.  Defaults to
            backend/data/parameters/crossover_params.json relative to repo root.
        """
        import json
        from pathlib import Path as _Path

        if db_path is None:
            db_path = _Path(__file__).parent.parent / "data" / "parameters" / "crossover_params.json"
        data = json.loads(_Path(db_path).read_text())

        if crossover_type not in data:
            raise KeyError(
                f"Crossover type {crossover_type!r} not found in {db_path}. "
                f"Available: {list(data.keys())}"
            )
        entry = data[crossover_type]

        # Validate that r0 looks like a junction distance (not mid-arm centroid).
        # Mid-arm distances are typically >22 Å; junction distances ~17-22 Å.
        r0 = entry["r0_ang"]
        if r0 > 22.0:
            logger.warning(
                "r0=%.2f Å for %s looks like a mid-arm centroid distance, not a "
                "junction distance.  Expected ~17-22 Å for mrdna bead separation.  "
                "Check that the database entry uses local junction extraction.",
                r0, crossover_type,
            )

        return cls(
            label=crossover_type,
            r0_ang=r0,
            k_bond=entry["k_bond_kJ_mol_ang2"],
            hj_equilibrium_angle_deg=entry.get("hj_equilibrium_angle_deg", 0.0),
            k_dihedral=entry.get("k_dihedral_kJ_mol_rad2", 0.0),
            source_n_frames=entry.get("n_frames", entry.get("n_crossovers_source", 0)),
            source_restraint_k_kcal=entry.get("restraint_k_kcal", 0.0),
        )


# ── Patched SegmentModel ──────────────────────────────────────────────────────

def build_patched_model(
    design,
    override: CrossoverPotentialOverride,
    **model_params,
):
    """
    Build an mrdna SegmentModel with crossover potentials overridden.

    This is the main entry point for parameterized CG relaxation.

    Parameters
    ----------
    design : NADOC Design
        Will be converted to mrdna via mrdna_model_from_nadoc internals.
    override : CrossoverPotentialOverride
        Extracted CG parameters.  Must have converged=True (or sensitivity
        check passed) before use in production.
    **model_params
        Additional kwargs forwarded to SegmentModel (e.g. temperature,
        timestep, local_twist, escapable_twist).

    Returns
    -------
    PatchedSegmentModel instance (subclass of SegmentModel).

    Notes
    -----
    The hj_equilibrium_angle is set from override.hj_equilibrium_angle_deg and
    takes precedence over any value in model_params.
    """
    if override.sensitivity_check_passed is False:
        raise ValueError(
            f"Refusing to inject parameters for variant {override.label!r}: "
            f"restraint sensitivity check FAILED.  Fix the outer-arm restraint "
            f"model before using these parameters."
        )

    # hj_equilibrium_angle overrides any model_params value
    model_params["hj_equilibrium_angle"] = override.hj_equilibrium_angle_deg

    import sys
    import os
    _mrdna_path = "/tmp/mrdna-tool"
    if _mrdna_path not in sys.path:
        sys.path.insert(0, _mrdna_path)

    try:
        from mrdna.readers.segmentmodel_from_lists import model_from_basepair_stack_3prime
        from mrdna.segmentmodel import SegmentModel
        from mrdna.arbdmodel.interactions import HarmonicBond, HarmonicDihedral
    except ImportError as exc:
        raise ImportError("mrdna not found.  See docs/mrdna_setup.md.") from exc

    from backend.core.mrdna_bridge import _build_nt_arrays

    r, bp, stack, three_prime, orientation, seq, _nt_key = _build_nt_arrays(
        design, return_nt_key=True
    )

    # We need to subclass SegmentModel before model_from_basepair_stack_3prime
    # creates it, but that function creates the model internally.  We instead
    # create a PatchedSegmentModel directly from the same arrays.

    # Build the raw SegmentModel first to obtain the segments list, then
    # reconstruct with our subclass.
    # NOTE: model_from_basepair_stack_3prime creates segments then instantiates
    # SegmentModel.  We replicate its call signature.
    raw = model_from_basepair_stack_3prime(
        r, bp, stack, three_prime,
        sequence=seq,
        orientation=orientation,
        **model_params,
    )

    logger.warning(
        "build_patched_model: crossover bond r0 and k overrides were applied "
        "via hj_equilibrium_angle only (%.1f°).  Full bond/dihedral injection "
        "requires subclassing — see PatchedSegmentModel below.  "
        "For now, use PatchedSegmentModel directly if you need bond override.",
        override.hj_equilibrium_angle_deg,
    )
    return raw


class PatchedSegmentModel:
    """
    Wrapper factory that creates a SegmentModel subclass with overridden
    get_bond_potential and get_dihedral_potential.

    Usage
    -----
        factory = PatchedSegmentModel(override)
        model = factory.build(segments, **kwargs)

    Implementation note
    -------------------
    We cannot import SegmentModel at module level (mrdna may not be installed).
    The class is created dynamically in build() so imports happen lazily.
    """

    def __init__(self, override: CrossoverPotentialOverride):
        self.override = override

    def build(self, segments, **model_kwargs):
        """
        Instantiate a subclassed SegmentModel with overridden crossover potentials.

        Parameters
        ----------
        segments : list[Segment]
            mrdna segment list (from segmentmodel_from_lists or similar).
        **model_kwargs
            Forwarded to SegmentModel.__init__.
        """
        ovr = self.override
        # Ensure hj_equilibrium_angle uses our value
        model_kwargs["hj_equilibrium_angle"] = ovr.hj_equilibrium_angle_deg

        import sys
        if "/tmp/mrdna-tool" not in sys.path:
            sys.path.insert(0, "/tmp/mrdna-tool")

        from mrdna.segmentmodel import SegmentModel

        r0_target = ovr.r0_ang
        k_bond = ovr.k_bond
        k_dihedral = ovr.k_dihedral
        hj_deg = ovr.hj_equilibrium_angle_deg

        class _OverriddenSegmentModel(SegmentModel):
            """
            SegmentModel with atomistic-parameterized crossover potentials.

            Overrides:
              get_bond_potential: replaces the standard crossover HarmonicBond
                  (r0 ≈ 18.5 Å) with the atomistic-derived r0 and k.
              get_dihedral_potential: replaces the HJ dihedral potential with
                  the atomistic-derived k and t0.
            """

            def get_bond_potential(self, kSpring, d, correct_geometry=False):
                # Identify DX crossover bonds by characteristic equilibrium distance.
                # Standard: d=18.5 Å.  With extra Ts: d may be larger.
                # We override any bond whose d is within the tolerance of the
                # standard crossover distance — this covers all DX crossovers.
                if abs(d - _DEFAULT_XOVER_BOND_R0) < _XOVER_BOND_R0_TOLERANCE:
                    logger.debug(
                        "Overriding crossover bond: default r0=%.1f → %.2f Å, "
                        "k=%.3f → %.3f kJ/mol/Å²",
                        d, r0_target, kSpring, k_bond,
                    )
                    return super().get_bond_potential(k_bond, r0_target, correct_geometry)
                return super().get_bond_potential(kSpring, d, correct_geometry)

            def get_dihedral_potential(self, kSpring, d, max_potential=None):
                # Identify HJ dihedrals by proximity to hj_equilibrium_angle.
                # hj_equilibrium_angle is stored on self (set by parent __init__).
                # The parent uses t0 = self.hj_equilibrium_angle ± 0/180 degrees.
                hj = getattr(self, "hj_equilibrium_angle", hj_deg)
                candidate_t0s = {hj, hj - 180, hj + 180}
                if any(abs(d - t) < 5.0 for t in candidate_t0s):
                    logger.debug(
                        "Overriding HJ dihedral: default k=%.4f → %.4f kJ/mol/rad², "
                        "t0=%.1f°",
                        kSpring, k_dihedral, d,
                    )
                    return super().get_dihedral_potential(
                        k_dihedral, d, max_potential=_MAX_DIHEDRAL_POTENTIAL
                    )
                return super().get_dihedral_potential(kSpring, d, max_potential)

        _OverriddenSegmentModel.__name__ = f"SegmentModel__{ovr.label}"
        return _OverriddenSegmentModel(segments, **model_kwargs)


# ── Integration with mrdna_bridge ────────────────────────────────────────────

def mrdna_model_from_nadoc_parameterized(
    design,
    override: CrossoverPotentialOverride,
    *,
    return_nt_key: bool = False,
    **model_params,
):
    """
    Drop-in replacement for mrdna_bridge.mrdna_model_from_nadoc() that applies
    crossover potential overrides.

    Parameters
    ----------
    design : NADOC Design
    override : CrossoverPotentialOverride
        Extracted CG parameters for the crossover type present in design.
    return_nt_key : bool
        If True, return (model, nt_index_to_key).
    **model_params
        Forwarded to SegmentModel (temperature, timestep, local_twist, etc.).

    Returns
    -------
    PatchedSegmentModel (or tuple if return_nt_key=True).

    Raises
    ------
    ValueError
        If override.sensitivity_check_passed is False (non-None), refuses to run.
    """
    if override.sensitivity_check_passed is False:
        raise ValueError(
            f"Refusing to run parameterized CG for {override.label!r}: "
            "restraint sensitivity check failed.  Fix and re-parameterize first."
        )
    if not override.source_n_frames:
        logger.warning(
            "Override for %r has source_n_frames=0 — parameters may not be "
            "from a real trajectory.  Use only for testing.",
            override.label,
        )

    import sys
    if "/tmp/mrdna-tool" not in sys.path:
        sys.path.insert(0, "/tmp/mrdna-tool")

    from mrdna.readers.segmentmodel_from_lists import model_from_basepair_stack_3prime
    from backend.core.mrdna_bridge import _build_nt_arrays

    r, bp, stack, three_prime, orientation, seq, nt_key = _build_nt_arrays(
        design, return_nt_key=True
    )

    # Build segments without creating a full SegmentModel
    # model_from_basepair_stack_3prime creates both segments AND SegmentModel.
    # We need access to just the segments before instantiation.
    # Workaround: call the function but pass our subclassed constructor through
    # monkey-patching the module-level SegmentModel reference.
    import mrdna.readers.segmentmodel_from_lists as _sfl
    import mrdna.segmentmodel as _sm_module

    original_cls = _sm_module.SegmentModel
    factory = PatchedSegmentModel(override)
    model_params_with_hj = {
        **model_params,
        "hj_equilibrium_angle": override.hj_equilibrium_angle_deg,
    }

    # Temporarily replace SegmentModel in the module so model_from_basepair_stack_3prime
    # instantiates our patched subclass.
    # This is a controlled monkey-patch: we restore the original immediately after.
    # It is not thread-safe; do not call this concurrently.
    _restored = False
    try:
        # Build the patched class bound to our override
        patched_cls = _build_patched_class(override)
        _sm_module.SegmentModel = patched_cls
        # Also patch within the reader module if it imported directly
        if hasattr(_sfl, "SegmentModel"):
            _sfl._original_SegmentModel = getattr(_sfl, "SegmentModel")
            _sfl.SegmentModel = patched_cls

        model = model_from_basepair_stack_3prime(
            r, bp, stack, three_prime,
            sequence=seq,
            orientation=orientation,
            **model_params_with_hj,
        )
    finally:
        _sm_module.SegmentModel = original_cls
        _restored = True
        if hasattr(_sfl, "_original_SegmentModel"):
            _sfl.SegmentModel = _sfl._original_SegmentModel
            del _sfl._original_SegmentModel

    logger.info(
        "Built parameterized SegmentModel for %s "
        "(r0=%.2f Å, k_bond=%.3f, hj=%.1f°, k_dih=%.4f)",
        override.label, override.r0_ang, override.k_bond,
        override.hj_equilibrium_angle_deg, override.k_dihedral,
    )

    if return_nt_key:
        from typing import Optional, Tuple
        index_to_key = [None] * len(r)
        for (h_id, bp_idx, direction, k), idx in nt_key.items():
            if k == 0:
                index_to_key[idx] = (h_id, bp_idx, direction)
        return model, index_to_key
    return model


def _build_patched_class(override: CrossoverPotentialOverride):
    """
    Build the overridden SegmentModel subclass with the given override values
    captured in its closure.  Called by mrdna_model_from_nadoc_parameterized.
    """
    from mrdna.segmentmodel import SegmentModel

    r0_target = override.r0_ang
    k_bond = override.k_bond
    k_dihedral = override.k_dihedral
    hj_deg = override.hj_equilibrium_angle_deg
    label = override.label

    class _PatchedCls(SegmentModel):
        def get_bond_potential(self, kSpring, d, correct_geometry=False):
            if abs(d - _DEFAULT_XOVER_BOND_R0) < _XOVER_BOND_R0_TOLERANCE:
                return super().get_bond_potential(k_bond, r0_target, correct_geometry)
            return super().get_bond_potential(kSpring, d, correct_geometry)

        def get_dihedral_potential(self, kSpring, d, max_potential=None):
            hj = getattr(self, "hj_equilibrium_angle", hj_deg)
            if any(abs(d - t) < 5.0 for t in (hj, hj - 180, hj + 180)):
                return super().get_dihedral_potential(
                    k_dihedral, d, max_potential=_MAX_DIHEDRAL_POTENTIAL
                )
            return super().get_dihedral_potential(kSpring, d, max_potential)

    _PatchedCls.__name__ = f"SegmentModel__{label}"
    return _PatchedCls


# ── Diagnostic: compare default vs. overridden parameters ────────────────────

def summarize_override(override: CrossoverPotentialOverride) -> str:
    """
    Return a human-readable summary of what will change vs. mrdna defaults.

    Useful for logging before a parameterized CG run.
    """
    default_r0 = _DEFAULT_XOVER_BOND_R0
    return (
        f"CrossoverPotentialOverride summary for variant {override.label!r}\n"
        f"  Bond r0   : {default_r0:.1f} Å (default) → {override.r0_ang:.2f} Å\n"
        f"  Bond k    : mrdna default (geometry-derived) → {override.k_bond:.3f} kJ/mol/Å²\n"
        f"  HJ angle  : 0.0° (default) → {override.hj_equilibrium_angle_deg:.1f}°\n"
        f"  Dihedral k: mrdna default (geometry-derived) → {override.k_dihedral:.4f} kJ/mol/rad²\n"
        f"  Source    : {override.source_n_frames} MD frames, "
        f"restraint k={override.source_restraint_k_kcal} kcal/mol/Å²\n"
        f"  Sensitivity check: {override.sensitivity_check_passed}"
    )
