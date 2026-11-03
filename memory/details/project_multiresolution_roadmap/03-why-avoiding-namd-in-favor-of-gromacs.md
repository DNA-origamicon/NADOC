# Why: Avoiding NAMD in Favor of GROMACS — supporting detail

[Topic head](../../project_multiresolution_roadmap.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## Why: Avoiding NAMD in Favor of GROMACS
MrDNA's publication pipeline ends at NAMD for atomistic runs. GROMACS is preferred here because:
- ~2–4× faster single-node GPU performance (NVIDIA benchmarks)
- Better AMD GPU support
- Lower memory footprint per atom
- Already integrated in NADOC (existing `gromacs_package.py`)
- AMBER OL15 / CHARMM36 force fields both well-validated for DNA in GROMACS
