"""Emit a Colvars configuration for a design's CPD weld pair.

The two reaction coordinates (:mod:`backend.core.cpd_metrics`) are both plain Colvars
components, which is why this is a text emitter and not a plugin:

* ``d_mid`` — a ``distance`` between two ``{C5, C6}`` atom groups. A two-atom group's
  centre of mass IS the C5=C6 bond midpoint, because both atoms are carbon.
* ``eta``   — a ``dihedral`` over (C5_a, C6_a, C6_b, C5_b).

**``atomNumbers`` is 1-BASED.** Colvars indexes atoms as NAMD does, from 1; the serials
carried on a weld pair are 0-based MDAnalysis indices. Getting this wrong does not error
— it restrains a *different, nearby* atom and produces a plausible, wrong free energy.
:func:`emit_colvars` is the only place that conversion happens.

Units on the wire are Colvars': **Angstrom** for ``d_mid``, **degrees** for ``eta``.
Internally everything else in this codebase carries d in nm, so conversion happens here
too rather than being sprinkled through callers.

The hand-written ``CPD_1xT/colvars_cpd_metrics.in`` is the format oracle this reproduces.

See ``memory/project_cpd_umbrella_sampling.md``.
"""
from __future__ import annotations

from typing import Sequence

# Colvars `width` — the bin/discretisation scale, not a restraint width.
_WIDTH_D_ANG = 0.01
_WIDTH_ETA_DEG = 1.0

#: van der Waals contact between ring midpoints [A]. A classical force field cannot be
#: pushed below this in any meaningful way — d0 (1.57 A) is a covalent bond, i.e. the
#: product, and reaching it is quantum-chemistry territory.
VDW_FLOOR_ANG = 3.4


def _fmt(value: float) -> str:
    """Trim trailing zeros so the emitted file reads like a hand-written one."""
    return f"{value:g}"


def colvar_blocks(pair: dict, *, suffix: str = "", d_width: float = _WIDTH_D_ANG,
                  d_extra: Sequence[str] = ()) -> str:
    """The two colvar definitions for one weld pair, without any bias.

    ``d_extra`` injects extra keywords INTO the d_mid colvar block — eABF needs
    ``extendedLagrangian`` and the ABF grid boundaries to live on the variable itself,
    not in a second block. ``d_width`` overrides the discretisation: for ABF this is the
    grid BIN SIZE, so the metrics default (0.01 A) would ask for hundreds of bins that
    never fill.
    """
    c5a = int(pair["c5_a"]) + 1
    c6a = int(pair["c6_a"]) + 1
    c5b = int(pair["c5_b"]) + 1
    c6b = int(pair["c6_b"]) + 1
    a = f"{pair.get('segid_a', '?')}:{pair.get('resid_a', '?')}"
    b = f"{pair.get('segid_b', '?')}:{pair.get('resid_b', '?')}"
    _extra = "\n".join(f"  {line}" for line in d_extra)
    return f"""\
# d_mid{suffix}: distance between the centres of the two {{C5,C6}} groups (A).
# A two-atom group's centre of mass IS the C5=C6 bond midpoint (both are carbon).
colvar {{
  name d_mid{suffix}
  width {_fmt(d_width)}
{_extra}
  distance {{
    group1 {{ atomNumbers {{ {c5a} {c6a} }} }}  # {a}: C5,C6 (1-based)
    group2 {{ atomNumbers {{ {c5b} {c6b} }} }}  # {b}: C5,C6 (1-based)
  }}
}}

# eta{suffix}: dihedral (C5_a, C6_a, C6_b, C5_b) (deg) — the twist between the two
# C5=C6 double bonds.
colvar {{
  name eta{suffix}
  width {_WIDTH_ETA_DEG}

  dihedral {{
    group1 {{ atomNumbers {{ {c5a} }} }}  # C5_a
    group2 {{ atomNumbers {{ {c6a} }} }}  # C6_a
    group3 {{ atomNumbers {{ {c6b} }} }}  # C6_b
    group4 {{ atomNumbers {{ {c5b} }} }}  # C5_b
  }}
}}
"""


def emit_colvars(pairs: Sequence[dict], *, mode: str = "metrics",
                 center_ang: float | None = None, force_constant: float = 2.0,
                 target_ang: float | None = None, target_num_steps: int = 10_000_000,
                 lower_ang: float = VDW_FLOOR_ANG, upper_ang: float = 12.0,
                 grid_width_ang: float = 0.1,
                 traj_freq: int = 500, restart_freq: int = 10000,
                 comment: str = "") -> str:
    """A complete Colvars config for the given weld pairs.

    ``mode``:

    * ``"metrics"``  — definitions only. Both CVs are recorded as passive observers;
      nothing is biased. This is what you run to get the unbiased baseline.
    * ``"umbrella"`` — adds a ``harmonic`` restraint on ``d_mid`` at ``center_ang``.
      One window of an umbrella ladder.
    * ``"smd"``      — a MOVING harmonic: the restraint centre walks from ``center_ang``
      to ``target_ang`` over ``target_num_steps``. This is how umbrella windows get their
      starting structures: pull the pair in slowly, then harvest the frame nearest each
      window centre (:func:`cpd_metrics.seed_windows`). Cheaper than building a geometric
      placer, and it is what the reference ``colvars_cpd_smd.in`` does.
    * ``"eabf"``     — puts ``d_mid`` on an extended Lagrangian and applies ``abf``, so
      the bias adapts instead of needing a window grid. In Colvars, declaring
      ``extendedLagrangian`` on a variable and then an ``abf`` bias over it IS eABF;
      there is no separate keyword.

    Multiple pairs get numbered suffixes so a 2xT design's four combinations can be
    recorded at once. Only the FIRST pair is ever biased — biasing several distances
    simultaneously couples them into one landscape nobody asked for.
    """
    usable = [p for p in pairs or [] if p.get("serials_resolved") is not False
              and all(k in p for k in ("c5_a", "c6_a", "c5_b", "c6_b"))]
    if not usable:
        raise ValueError("no weld pair with resolved C5/C6 serials to emit")
    if mode not in ("metrics", "umbrella", "eabf", "smd"):
        raise ValueError(f"unknown mode {mode!r}")
    if mode in ("umbrella", "smd") and center_ang is None:
        raise ValueError(f"{mode} mode needs center_ang")
    if mode == "smd" and target_ang is None:
        raise ValueError("smd mode needs target_ang")

    head = ["# Colvars for the designed extra-base UV weld (CPD).",
            "# Generated by NADOC — backend/core/cpd_colvars.py."]
    if comment:
        head += [f"# {line}" for line in comment.splitlines()]
    head += [
        "#",
        "# d_mid is the distance between the two C5=C6 BOND MIDPOINTS, which is the",
        "# coordinate the KIMMDY geometric rate model is a function of — not C5-C5.",
        "# The product geometry (d0 = 1.57 A) is a covalent bond: a classical force field",
        f"# cannot reach it. Useful range bottoms out at vdW contact, ~{_fmt(VDW_FLOOR_ANG)} A.",
        "",
        f"colvarsTrajFrequency     {traj_freq}",
        f"colvarsRestartFrequency  {restart_freq}",
        "",
    ]

    # eABF puts the grid + extended-Lagrangian keywords on the variable itself.
    d_extra: list[str] = []
    d_width = _WIDTH_D_ANG
    if mode == "eabf":
        d_width = grid_width_ang
        d_extra = [
            f"lowerBoundary {_fmt(float(lower_ang))}",
            f"upperBoundary {_fmt(float(upper_ang))}",
            "extendedLagrangian on",
            # Comparable to the grid width, per the Colvars guidance: much smaller and
            # the extended variable is too stiff to smooth anything.
            f"extendedFluctuation {_fmt(float(grid_width_ang))}",
        ]

    body = []
    for i, pair in enumerate(usable):
        suffix = "" if len(usable) == 1 else f"_{i + 1}"
        body.append(f"# pair: {pair.get('label', pair.get('id', '?'))}")
        # Only the FIRST pair carries the bias keywords; the rest are observers.
        body.append(colvar_blocks(pair, suffix=suffix,
                                  d_width=d_width if i == 0 else _WIDTH_D_ANG,
                                  d_extra=d_extra if i == 0 else ()))

    primary = "" if len(usable) == 1 else "_1"
    bias = []
    if mode == "umbrella":
        bias = [
            "# One umbrella window. The partner coordinate eta rides along as a passive",
            "# observer — it is recorded, not restrained, so the window samples whatever",
            "# twist the structure prefers at this separation.",
            "harmonic {",
            f"    colvars       d_mid{primary}",
            f"    centers       {_fmt(float(center_ang))}",
            f"    forceConstant {_fmt(float(force_constant))}",
            "    outputEnergy  yes",
            "}",
            "",
        ]
    elif mode == "smd":
        bias = [
            "# Steered MD: the restraint centre WALKS from `centers` to `targetCenters`",
            "# over `targetNumSteps`, dragging the pair through every window separation on",
            "# the way. Harvest the frame nearest each window centre to seed the ladder.",
            "# Keep the force constant low and the pull slow — a fast pull does work on the",
            "# structure that the umbrella windows then have to relax back out.",
            "harmonic {",
            f"    colvars        d_mid{primary}",
            f"    centers        {_fmt(float(center_ang))}",
            f"    targetCenters  {_fmt(float(target_ang))}",
            f"    targetNumSteps {int(target_num_steps)}",
            f"    forceConstant  {_fmt(float(force_constant))}",
            "    outputEnergy   yes",
            "}",
            "",
        ]
    elif mode == "eabf":
        bias = [
            "# eABF: the bias adapts as it samples, so no window ladder, no per-window",
            "# seeds and no WHAM/MBAR. Declaring extendedLagrangian ON THE VARIABLE and an",
            "# abf bias over it IS eABF in Colvars — there is no separate keyword, and the",
            "# keywords must live in the colvar block above, not in one of their own.",
            "# Read the CZAR estimator from the output, not the naive ABF gradient.",
            "abf {",
            f"    colvars        d_mid{primary}",
            "    # No bias applied until a bin has this many samples, so early noise is",
            "    # not amplified into a bias that then has to be unlearned.",
            "    fullSamples    500",
            "    historyFreq    100000",
            "    outputFreq     10000",
            "}",
            "",
        ]

    return "\n".join(head) + "\n".join(body) + "\n" + "\n".join(bias)


def umbrella_windows(d_start_ang: float, d_end_ang: float, *,
                     spacing_ang: float = 0.5, wide_spacing_ang: float = 1.0,
                     dense_below_ang: float = 7.0,
                     k_near: float = 3.0, k_far: float = 1.0) -> list[dict]:
    """A window ladder from ``d_start_ang`` out to ``d_end_ang``.

    Follows the shape the AutoNAMD campaigns converged on (reference only — those runs
    are not production data here): **dense spacing and a stiffer spring at short range**,
    coarser and softer further out. The reasoning is that the free energy varies fastest
    where the two rings are actually interacting, and a window there needs a stiffer
    restraint to hold its centre against a steep gradient.

    Returns ``[{center_ang, force_constant}, …]`` ascending. The caller decides how long
    to run each; overlap between neighbours is what MBAR needs and is worth checking
    before spending GPU time on the whole ladder.
    """
    if d_end_ang <= d_start_ang:
        raise ValueError("d_end_ang must exceed d_start_ang")
    span = max(float(spacing_ang), 1e-3), max(float(wide_spacing_ang), 1e-3)
    out: list[dict] = []
    d = float(d_start_ang)
    while d <= float(d_end_ang) + 1e-9:
        near = d < dense_below_ang
        out.append({"center_ang": round(d, 3),
                    "force_constant": float(k_near if near else k_far)})
        d += span[0] if near else span[1]
    return out
