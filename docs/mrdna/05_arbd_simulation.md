# Stage 4 — ARBD Simulation

ARBD (Adaptively Restrained Brownian Dynamics) is the coarse-grained
dynamics engine that mrdna uses for both coarse and fine stages.

---

## What ARBD Simulates

ARBD is a **Brownian dynamics** (overdamped Langevin) integrator for
point particles.

**Degrees of freedom** (per bead):
- 3 translational: x, y, z position
- (Fine stage only) Twist is encoded implicitly through the DNA→O bond
  vector; ARBD does not have explicit rotational DOF for individual beads.

The force field (harmonic bonds, WLC, Debye-Hückel, excluded volume, angle
and dihedral terms) is evaluated each step.

---

## Input Files

| File | Contents |
|------|----------|
| `{name}.psf` | NAMD-format PSF: atom types, masses, charges, bond/angle/dihedral lists |
| `{name}.pdb` | Initial bead coordinates (Å) |
| `{name}.particles.txt` | ARBD-specific particle type parameters (mass, diffusion coefficient) |
| `potentials/{name}.bond.txt` | Tabulated 1-D bond potentials |
| `potentials/{name}.angle.txt` | Tabulated 1-D angle potentials |
| `potentials/{name}.dihedral.txt` | Tabulated 1-D dihedral potentials |
| `potentials/{name}.exclusion.txt` | Non-bonded exclusion list |

---

## Output Files

| File | Contents |
|------|----------|
| `output/{name}.dcd` | Binary DCD trajectory — bead positions (Å) at each `output_period` step |
| `output/{name}.restart` | Plain-text restart file — final bead positions (Å), one line per bead: `idx  x  y  z` |
| Log (stdout) | Energy, force, step information |

**DCD format**: standard VMD/NAMD binary DCD.  Each frame contains N×3
floats (x, y, z in Å for all N beads).  Compatible with MDAnalysis,
VMD, NAMD.

**Restart format**: plain text, one bead per line:
```
0   x0  y0  z0
1   x1  y1  z1
...
```

---

## Coordinate Frame

ARBD uses **exactly the input coordinate frame**.  No rotation or
translation is applied.  For mrdna models built from NADOC coordinates
the frame is the NADOC world frame (origin at NADOC 0,0,0; units Å).

PBC: ARBD uses a finite rectangular box.  Default dimensions are 5000 Å³
(large enough that most DNA origami structures do not self-interact across
periodic boundaries).

---

## Timestep and Step Counts

| Stage | `local_twist` | Timestep | Typical steps |
|-------|--------------|----------|---------------|
| Coarse | False | 200 μs | 5 × 10⁷ |
| Fine | True | 40 μs | 5 × 10⁷ |

The Langevin thermostat is applied at each step with friction derived from
the particle diffusion coefficient.  Temperature defaults to 291 K (18 °C).

---

## Multi-Stage Protocol (simulate.py)

The `simulate()` function in `mrdna/simulate.py` orchestrates multiple
ARBD passes with spline updates between them:

```
1. generate_bead_model(max_bp=5, local_twist=False)
2. ARBD: 50M steps (coarse)       → update_splines
   [optional repeat with fresh bead model if bond_cutoff active]
3. generate_bead_model(max_bp=1, local_twist=True)
4. ARBD: 50M steps (fine)         → update_splines
5. generate_atomic_model()        [or NADOC bridge reads fine DCD]
```

---

## dry_run Mode

When `num_steps=0` (or `dry_run=True`) is passed to `engine.simulate()`:
- `prepare_for_simulation()` is called (no-op by default).
- Input files are written (PSF, PDB, particle/potential files).
- **ARBD is not executed.**
- Output files (DCD, restart) are not created.

This is how NADOC captures the **initial coarse PSF/PDB** — the pre-
simulation starting geometry in the NADOC coordinate frame — without
running any dynamics.

---

## ARBD vs GROMACS

| Feature | ARBD (coarse/fine) | GROMACS (atomistic) |
|---------|-------------------|---------------------|
| Resolution | 1 bead / 5 bp (coarse) or 1 bp (fine) | Every heavy atom |
| Force field | WLC + Debye-Hückel | CHARMM36 |
| Solvent | Implicit (Langevin) | Explicit TIP3P water |
| Timestep | 40–200 μs | 2 fs |
| Simulation speed | ~10 μs/day (coarse) | ~50 ns/day (atomistic) |
| Primary output | Bead trajectories (DCD) | Atomic trajectories (XTC) |
