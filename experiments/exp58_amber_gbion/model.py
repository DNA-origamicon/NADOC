"""Static configuration for the native Amber26 OL15/GBION validation.

This module deliberately has no Amber, OpenMM, or RunPod dependency.  It is used by
the local preflight and by the pod worker, so every launch is generated from the same
salt-count and mdin definitions.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path


AVOGADRO_PER_ANGSTROM3_MOLAR = 6.02214076e-4
EXPECTED_AMBER_ARCHIVE = "pmemd26.tar.bz2"
EXPECTED_AMBER26_BYTES = 349_473_241
EXPECTED_AMBER26_MD5 = "ceeabc133e772c115183d5cf6a87676b"
EXPECTED_AMBER26_SHA256 = (
    "0478ccce892f3525e995e9c85458d552c6060b73dd28acd03c366e61ecf23a14"
)


@dataclass(frozen=True)
class GBIONNaClConfig:
    """Configuration used by exp58's tested GBION-v3 NaCl variant.

    This preserves experiment provenance.  It is not the literature-matched
    accelerated-sampling protocol; see FINAL_ASSESSMENT.md before any reuse.
    """

    concentration_molar: float = 0.150
    sphere_radius_angstrom: float = 40.0
    solute_volume_angstrom3: float = 0.0
    temperature_kelvin: float = 300.0
    collision_frequency_ps: float = 1.0
    timestep_ps: float = 0.002
    random_seed: int = 20260827
    ion_wall_kcal_mol_angstrom2: float = 20.0

    def validate(self) -> None:
        if self.concentration_molar <= 0:
            raise ValueError("concentration_molar must be positive")
        if self.sphere_radius_angstrom <= 0:
            raise ValueError("sphere_radius_angstrom must be positive")
        sphere_volume = 4.0 * math.pi * self.sphere_radius_angstrom**3 / 3.0
        if not 0 <= self.solute_volume_angstrom3 < sphere_volume:
            raise ValueError("solute volume must be nonnegative and smaller than the sphere")
        if self.timestep_ps <= 0:
            raise ValueError("timestep_ps must be positive")

    @property
    def solvent_volume_angstrom3(self) -> float:
        self.validate()
        sphere = 4.0 * math.pi * self.sphere_radius_angstrom**3 / 3.0
        return sphere - self.solute_volume_angstrom3

    def ion_counts(self, solute_charge_e: int) -> tuple[int, int]:
        """Return neutral Na+/Cl- counts using Amber's documented SLTCAP equation.

        Rounding the co-ion count first and enforcing exact electroneutrality avoids an
        independently rounded pair whose difference can miss the integral solute charge.
        The return order is ``(n_na, n_cl)``.
        """

        bulk_particles = (
            self.solvent_volume_angstrom3
            * self.concentration_molar
            * AVOGADRO_PER_ANGSTROM3_MOLAR
        )
        charge_term = solute_charge_e / (2.0 * bulk_particles)
        common = math.sqrt(charge_term * charge_term + 1.0)
        raw_na = bulk_particles * (common - charge_term)
        raw_cl = bulk_particles * (common + charge_term)
        if solute_charge_e <= 0:
            n_cl = max(0, round(raw_cl))
            n_na = n_cl - solute_charge_e
        else:
            n_na = max(0, round(raw_na))
            n_cl = n_na + solute_charge_e
        if solute_charge_e + n_na - n_cl != 0:
            raise AssertionError("SLTCAP counts did not neutralize the system")
        return n_na, n_cl


# Preserve the exact exp58 input for reproducibility.  The published paper and the
# Amber25 manual specify 8.0, not 10.0, for the anion-related dielectric coefficients.
# Do not reuse this constant as a literature-matched production template.
GBION_NACL_NAMELIST = """\
  igb=8, gbion=3, alpb=0, gbsa=3,
  intdiel=1.0, extdiel=78.5, saltcon=0.0,
  gi_coef_1_n=0.05, gi_coef_2_pn=0.05,
  intdiel_ion_1_p=54.0, intdiel_ion_1_n=10.0,
  intdiel_ion_2_pp=54.0, intdiel_ion_2_pn=10.0,
  intdiel_ion_2_nn=10.0,
"""


def render_production_mdin(
    config: GBIONNaClConfig,
    *,
    steps: int,
    trajectory_interval: int = 5_000,
    restart: bool = True,
    disang_name: str = "disang_NaCl.txt",
) -> str:
    """Render an unrestrained-DNA, ion-confined GBION production input."""

    config.validate()
    if steps <= 0:
        raise ValueError("steps must be positive")
    if trajectory_interval <= 0:
        raise ValueError("trajectory_interval must be positive")
    ntx = 5 if restart else 1
    irest = 1 if restart else 0
    return f"""Native Amber26 OL15 + GBneck2/GBION-v3, explicit 150 mM NaCl
 &cntrl
  imin=0, irest={irest}, ntx={ntx},
  nstlim={steps}, dt={config.timestep_ps:.6f},
  ntt=3, tempi={config.temperature_kelvin:.3f},
  temp0={config.temperature_kelvin:.3f},
  gamma_ln={config.collision_frequency_ps:.6f}, ig={config.random_seed},
  ntb=0, ntp=0, ntc=2, ntf=2, cut=1000.0,
  ntpr={trajectory_interval}, ntwx={trajectory_interval},
  ntwr={steps}, ioutfm=1, ntxo=2,
  nmropt=1,
{GBION_NACL_NAMELIST} /
 &wt type='END' /
 DISANG={disang_name}
 LISTIN=POUT
 LISTOUT=POUT
"""


def render_ion_restraints(
    phosphorus_atom_indices: list[int] | tuple[int, ...],
    ion_atom_indices: list[int] | tuple[int, ...],
    config: GBIONNaClConfig,
) -> str:
    """Render Amber flat-bottom group-to-ion distance restraints.

    Amber atom indices are one-based.  ``iat=-1,<ion>`` makes ``igr1`` the
    coordinate-averaged phosphorus group; because every member is phosphorus,
    that point is also its center of mass.  The interval ``r2..r3`` is flat and
    ``rk3`` applies only outside the spherical boundary.
    """

    config.validate()
    phosphorus = [int(index) for index in phosphorus_atom_indices]
    ions = [int(index) for index in ion_atom_indices]
    if not phosphorus or not ions:
        raise ValueError("phosphorus and ion atom-index lists must be nonempty")
    if any(index <= 0 for index in phosphorus + ions):
        raise ValueError("Amber restraint atom indices must be one-based")
    if len(set(phosphorus)) != len(phosphorus):
        raise ValueError("phosphorus atom indices must be unique")
    if len(set(ions)) != len(ions):
        raise ValueError("ion atom indices must be unique")

    group = ",".join(str(index) for index in phosphorus) + ",0"
    blocks = []
    for ion in ions:
        blocks.append(
            "&rst\n"
            f"  iat=-1,{ion},\n"
            "  r1=0.0, r2=0.0, "
            f"r3={config.sphere_radius_angstrom:.6f}, r4=999.0,\n"
            "  rk2=0.0, "
            f"rk3={config.ion_wall_kcal_mol_angstrom2:.6f},\n"
            f"  igr1={group},\n"
            "/"
        )
    return "\n".join(blocks) + "\n"


def require_amber26_archive(path: Path) -> Path:
    """Validate the licensed package before any pod can be created."""

    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(
            f"Amber26 package not found: {resolved}. Download {EXPECTED_AMBER_ARCHIVE} "
            "after accepting the Amber license; no RunPod pod was created."
        )
    if resolved.name != EXPECTED_AMBER_ARCHIVE:
        raise ValueError(
            f"expected the Amber26 pmemd archive named {EXPECTED_AMBER_ARCHIVE}, "
            f"got {resolved.name}"
        )
    if resolved.stat().st_size != EXPECTED_AMBER26_BYTES:
        raise ValueError(
            f"{resolved} has {resolved.stat().st_size} bytes; the published Amber26 "
            f"archive has {EXPECTED_AMBER26_BYTES}"
        )
    return resolved
