"""Admit PSF parsing before allocating its Python topology and coordinate buffers."""
from pathlib import Path


def open_universe(topology, *coordinates, **kwargs):
    import MDAnalysis as mda
    from backend.core.memory_budget import reserve, MIB
    from backend.core.namd_resources import psf_atoms

    if isinstance(topology, (str, Path)) and Path(topology).suffix.lower() == '.psf':
        amount = 256*MIB + psf_atoms(topology)*768
    elif hasattr(topology, 'n_atoms'):
        amount = 128*MIB + int(topology.n_atoms)*64
    else:
        # Non-PSF readers retain their existing path; the NAMD envelope does not
        # characterize other engines' file formats.
        return mda.Universe(topology, *coordinates, **kwargs)
    with reserve(amount, label='MD topology and frame loading'):
        return mda.Universe(topology, *coordinates, **kwargs)
