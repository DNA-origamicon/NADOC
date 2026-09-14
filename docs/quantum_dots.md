# Quantum-dot catalog and import

Tools → Nanoparticle → Quantum dot opens a searchable vendor catalog. Select a row
to inspect the size specification and the full published absorption/emission plot.
Import creates a rigid, display-layer nanoparticle and selects its shared Move/Rotate
gizmo. The dot supports the same picking, Apply, Cancel, Reset, undo/redo, and
save/reload paths as a gold nanosphere.

The initial catalog contains 11 importable NN-Labs HECZ products (450–660 nm emission)
and 12 preview-only Thermo Fisher Qdot variants: eight streptavidin, three carboxyl,
and one amino-PEG. The table has distinct coating and functionalization columns.
Functionalized imports are disabled in both the UI and API. Quantum dots cannot enter
the gold thiol conjugation workflow.

## Vendor data and size conventions

- [NN-Labs HECZ product page](https://nn-labs.com/products/high-efficiency-cadmium-selenide-zinc-sulfide-cdse-zns-quantum-dots-cz)
- [NN-Labs size specifications, September 2022](https://cdn.shopify.com/s/files/1/0255/7306/4776/files/HECZ_Technical_Specifications_updated_9-16-22.pdf?v=1663343923)
- [NN-Labs absorption/emission plots](https://cdn.shopify.com/s/files/1/0255/7306/4776/files/HECZ_Sample_Spectra_d3e1c293-0715-493a-a198-993a73d1ee31.pdf?v=1660058100)
- [Thermo Fisher Qdot manual, Figure 2 on page 3](https://documents.thermofisher.com/TFS-Assets/LSG/manuals/mp19020.pdf)
- [Thermo Fisher size FAQ](https://www.thermofisher.com/order/catalog/product/Q21541MP/faqs)
- [Thermo Fisher Qdot product families and streptavidin catalog numbers](https://www.thermofisher.com/us/en/home/references/molecular-probes-the-handbook/ultrasensitive-detection-technology/qdot-nanocrystal-technology.html)

HECZ sizes are vendor total nanocrystal diameters, with separate core ranges. The
scene diameter defaults to the midpoint of the total range and can be adjusted
within that range. It is a spherical scene approximation, not a lot measurement.
The vendor does not specify the ligand envelope. HECZ450 is CdS/ZnS, unlike the
other HECZ entries (CdSe/ZnS). Product numbers denote emission, not absorption.

Thermo's 15–21 nm size is an approximate family-wide hydrodynamic range for fully
functionalized dots. It must not be read as a per-product core diameter. The catalog
labels this explicitly and does not infer an uncoated diameter from emission.
The Thermo plot is a family reference, not a separate measured lot for each coating.

## Spectral provenance and persistence

The bundled PNGs preserve the original vendor curves and published wavelength
ranges. HECZ450–650 images are extracted directly from PDF image objects; HECZ660
and the Qdot family figure are rendered from their PDF vector plots. These are
vendor plots, not raw numerical samples or fitted/synthetic spectra. No Gaussian
curves or absorption tails are invented. Spectral computation/FRET is not part of
this import step.

`backend/data/quantum_dots/catalog.json` pins the catalog version, source URLs,
source page, plot checksum, size basis, coating, and import policy. The imported
`Nanoparticle.quantum_dot` holds a snapshot of its catalog provenance. Scene size
and rigid pose are ordinary nanoparticle fields. The frontend bundles the catalog and plot previews so opening it does not wait
behind simulation-status requests. The local plot endpoint also serves these assets
for API clients. Browsing/importing needs no live vendor connection. Updating a catalog does not rewrite existing design records.

Regenerate the assets and catalog with:

```sh
uv run --no-project --with pymupdf --with httpx python scripts/build_quantum_dot_catalog.py
```

The extraction dependencies are development tools only. Review changed vendor
specifications and page layouts before updating the catalog version.

Editing lifecycle: import, movement, scene-diameter changes, and deletion use the
shared nanoparticle snapshot feature log and undo/redo stack. Rebuilding after a
commit or history restore reanchors the gizmo at the restored center. The import
entry's diameter editor remains available after later operations while the dot
exists. Delete works on selected nanoparticles. Undo keeps the document open,
including after removing its last object. Automatic default-animation creation
is idempotent display initialization and does not add an unrelated undo step or
clear redo history.

View → Fluorescence enables each quantum dot's catalog emission-color material
and a soft halo scaled to its diameter. These are approximate display hues, not
calibrated spectral rendering. Halos follow live movement and history restores;
toggling the mode changes no design data or undo history. Gold particles retain
their metallic appearance.

## Gold quenching

See [gold quenching research and rendering](gold_quenching.md). The FRET Checker
now reports QD–gold pairs explicitly, including live separation and missing
calibration. Current vendor dots retain reference emission because a validated
gold size/donor/coating quenching curve is not available in their catalog data.
An unknown pair is not a prediction of zero quenching.

Custom PDB-based streptavidin coatings can now be applied to imported dots through
**Streptavidin coating…** in the particle context menu. These use an explicitly
labeled geometric loading estimate, not a vendor's measured loading. Vendor
streptavidin presets remain disabled because their reported hydrodynamic sizes do
not establish the inorganic core size. See the [coating implementation and
simulation audit](streptavidin_simulation_audit.md).
