"""Rebuild the bundled vendor catalog and original spectral plot assets.

Run from the repository root:
  uv run --no-project --with pymupdf --with httpx python scripts/build_quantum_dot_catalog.py

Requires no runtime dependency changes. Sizes are transcribed from the linked vendor
specifications; curves are extracted/rendered from the original PDFs, never fitted.
Review upstream document changes before updating the catalog version.
"""
from pathlib import Path
import hashlib
import json

import httpx
import pymupdf

OUT = Path(__file__).resolve().parents[1] / 'backend/data/quantum_dots'
VERSION = '2026-09-12'
HECZ_PRODUCT = 'https://nn-labs.com/products/high-efficiency-cadmium-selenide-zinc-sulfide-cdse-zns-quantum-dots-cz'
HECZ_SPECTRA = 'https://cdn.shopify.com/s/files/1/0255/7306/4776/files/HECZ_Sample_Spectra_d3e1c293-0715-493a-a198-993a73d1ee31.pdf?v=1660058100'
HECZ_SIZE = 'https://cdn.shopify.com/s/files/1/0255/7306/4776/files/HECZ_Technical_Specifications_updated_9-16-22.pdf?v=1663343923'
QDOT_SPECTRA = 'https://documents.thermofisher.com/TFS-Assets/LSG/manuals/mp19020.pdf'
QDOT_SIZE = 'https://www.thermofisher.com/order/catalog/product/Q21541MP/faqs'
COLORS = {450:'#5252ff',470:'#328aff',500:'#00c9b7',520:'#45ce65',540:'#85ca35',560:'#b9bc28',580:'#e5ac25',600:'#f78d29',620:'#f25f36',650:'#e63946',660:'#ce365b',525:'#58d65d',565:'#c5c731',585:'#efb02e',605:'#f18a32',625:'#eb593e',655:'#da3b51',705:'#aa547d',800:'#9369bf'}
HECZ_ROWS = [
    (450,(2,2.5),(7,8)), (470,(2,2.5),(8,9)), (500,(2.5,3),(8,9)),
    (520,(2.5,3),(9,10)), (540,(2.5,3),(10,11)), (560,(3,3.5),(8,9)),
    (580,(3,3.5),(9,10)), (600,(3.5,4),(9,10)), (620,(3.5,4),(10,11)),
    (650,(4,4.5),(11,12)), (660,(4.5,5),(14,16)),
]


def fetch_pdf(url, expected_pages):
    response = httpx.get(url, follow_redirects=True, timeout=60)
    response.raise_for_status()
    doc = pymupdf.open(stream=response.content, filetype='pdf')
    if len(doc) != expected_pages or 'Access Denied' in doc[0].get_text():
        raise ValueError(f'Unexpected vendor document: {url}')
    return doc


def spectra(url, page, filename, note):
    return dict(source_url=url, source_page=page, plot_file=filename,
                sha256=hashlib.sha256((OUT / filename).read_bytes()).hexdigest(),
                format='vendor_plot', note=note)


def main():
    hecz = fetch_pdf(HECZ_SPECTRA, 11)
    qdot = fetch_pdf(QDOT_SPECTRA, 11)
    OUT.mkdir(parents=True, exist_ok=True)
    entries = []
    for i,(wl,core,total) in enumerate(HECZ_ROWS):
        page = hecz[i]
        if f'HECZ{wl}' not in page.get_text():
            raise ValueError(f'HECZ page mapping changed: {wl}')
        filename = f'hecz-{wl}.png'
        if i < 10:
            im = max(page.get_images(full=True), key=lambda im: im[2]*im[3])
            pymupdf.Pixmap(hecz, im[0]).save(OUT / filename)
        else:
            page.get_pixmap(matrix=pymupdf.Matrix(2,2), clip=pymupdf.Rect(130,225,485,472)).save(OUT / filename)
        entries.append(dict(
            catalog_id=f'nn-hecz-{wl}', catalog_version=VERSION, vendor='NN-Labs / NNCrystal',
            product_name=f'HECZ {wl}', product_code=f'HECZ{wl}-10', product_url=HECZ_PRODUCT,
            composition='CdS/ZnS' if wl == 450 else 'CdSe/ZnS', emission_peak_nm=wl,
            absorption_peak_nm=wl-10, emission_tolerance_nm=10, absorption_tolerance_nm=10,
            diameter_range_nm=total, core_diameter_range_nm=core,
            size_basis='Vendor total nanocrystal diameter (core + shell); ligand envelope not specified.',
            size_source_url=HECZ_SIZE, surface_coating='Oleic acid stabilizing ligands',
            functionalization='None (no affinity ligand)', import_enabled=True,
            display_color=COLORS[wl], spectra=spectra(HECZ_SPECTRA, i+1, filename,
                'Original vendor absorption and emission curves in arbitrary units. Generic product spectra; actual lots vary by ±10 nm. Full published plot, not numerical samples.'),
        ))
    qdot[2].get_pixmap(matrix=pymupdf.Matrix(2,2), clip=pymupdf.Rect(200,60,568,232)).save(OUT/'qdot-family.png')
    variants = [
        ('Streptavidin', 'streptavidin', [(525,'Q10141MP'),(565,'Q10131MP'),(585,'Q10111MP'),(605,'Q10101MP'),(625,'Q22063'),(655,'Q10121MP'),(705,'Q10161MP'),(800,'Q10171MP')]),
        ('Carboxyl', 'carboxyl', [(525,'Q21341MP'),(605,'Q21301MP'),(655,'Q21321MP')]),
        ('Amine (PEG)', 'amine-peg', [(525,'Q21541MP')]),
    ]
    for label,key,products in variants:
        for wl,code in products:
            entries.append(dict(
                catalog_id=f'thermo-qdot-{wl}-{key}', catalog_version=VERSION,
                vendor='Thermo Fisher / Invitrogen', product_name=f'Qdot {wl}', product_code=code,
                product_url=f'https://www.thermofisher.com/order/catalog/product/{code}',
                composition='CdSeTe/ZnS' if wl >= 705 else 'CdSe/ZnS', emission_peak_nm=wl,
                absorption_peak_nm=None, diameter_range_nm=[15,21], core_diameter_range_nm=None,
                size_basis='Approximate family-wide hydrodynamic diameter of fully functionalized Qdots; not a product-specific core size.',
                size_source_url=QDOT_SIZE, surface_coating='Amphiphilic polymer' + (' + PEG' if key != 'carboxyl' else ''),
                functionalization=label, import_enabled=False,
                disabled_reason='Functionalized-dot import is not enabled yet.', display_color=COLORS[wl],
                spectra=spectra(QDOT_SPECTRA, 3, 'qdot-family.png',
                    'Vendor family reference curves, Figure 2: 525 (1), 565 (2), 585 (3), 605 (4), 625 (5), 655 (6), 705 (7), 800 (8). Not a lot-specific measurement or numerical dataset.'),
            ))
    (OUT/'catalog.json').write_text(json.dumps(dict(version=VERSION, entries=entries), indent=2)+'\n')


if __name__ == '__main__':
    main()
