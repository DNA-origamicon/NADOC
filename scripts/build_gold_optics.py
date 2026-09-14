"""Rebuild offline sphere spectra: uv run --no-project --with miepython==3.0.2 --with pyyaml python scripts/build_gold_optics.py"""
import json
from pathlib import Path

import miepython
import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'backend/data/photophysics'
source = yaml.safe_load((DATA / 'gold_johnson_christy.yml').read_text())
nk = np.array([list(map(float, row.split())) for row in source['DATA'][0]['data'].splitlines()])
wavelengths = np.arange(400, 802, 2)
index = np.interp(wavelengths / 1000, nk[:, 0], nk[:, 1]) - 1j * np.interp(wavelengths / 1000, nk[:, 0], nk[:, 2])
spectra = []
for diameter in range(5, 101):
    ext, sca, _, _ = miepython.efficiencies(index, diameter, wavelengths, n_env=1.333)
    area = np.pi * (diameter / 2) ** 2
    absorption = (ext - sca) * area
    assert np.all(absorption >= 0)
    spectra.append({'diameter_nm': diameter,
                    'extinction_nm2': np.round(ext * area, 5).tolist(),
                    'absorption_nm2': np.round(absorption, 5).tolist()})
output = {
    'version': 1,
    'model': 'Mie sphere; bulk Johnson–Christy gold; water n=1.333; no coating',
    'generator': 'miepython==3.0.2',
    'optical_constants_source': 'https://doi.org/10.1103/PhysRevB.6.4370',
    'optical_constants_download': 'https://raw.githubusercontent.com/polyanskiy/refractiveindex.info-database/master/database/data/main/Au/nk/Johnson.yml',
    'vendor_source': 'https://nanocomposix.com/pages/standard-product-specifications',
    'vendor_series': 'BioPure Gold Nanospheres; nominal specifications, accessed 2026-09-12',
    # Diameter, peak wavelength, peak OD/cm, particles/mL (vendor table).
    'vendor_reference': [
        [5,520,16.0,7.91e14], [7,520,16.4,2.88e14], [10,520,16.4,9.88e13],
        [15,520,16.6,2.92e13], [20,520,16.9,1.24e13], [30,520,22.1,3.66e12],
        [40,520,22.6,1.54e12], [50,525,29.1,7.90e11], [60,530,31.8,4.58e11],
        [70,535,31.8,2.88e11], [80,545,31.5,1.93e11], [100,555,20.1,9.88e10]],
    'wavelength_nm': wavelengths.tolist(), 'spectra': spectra,
}
(DATA / 'gold_optics.json').write_text(json.dumps(output, separators=(',', ':')) + '\n')
print('Wrote', len(spectra), 'size-dependent spectra')
