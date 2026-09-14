# Gold creation optical references

Tools → Nanoparticle → Gold nanosphere opens the creation popup. Enter a core
diameter to update the absorption/extinction/scattering spectra, peak wavelengths
and molar extinction coefficient. The wavelength slider inspects individual
spectral points. Coatings are configured separately in Conjugate Manager;
see [coating implementation and simulation audit](streptavidin_simulation_audit.md).
The displayed optical curves remain uncoated-core references. Creation
uses the existing gold API, selection, movement and undo/redo path; diameter
editing retains its existing prompt.

The offline reference grid covers 5–100 nm diameter in 1 nm increments and
400–800 nm vacuum wavelength in 2 nm increments. Fractional diameters interpolate
cross sections. Scene sizes outside that range remain allowed (0 < d ≤ 1000 nm),
but no optical values are extrapolated.

Spectra are **calculated reference estimates**, using Mie theory for a homogeneous
isolated gold sphere in water (constant refractive index 1.333), with room-temperature
[Johnson & Christy bulk optical constants](https://doi.org/10.1103/PhysRevB.6.4370).
The bundled optical-constant table comes from the CC0
[refractiveindex.info database](https://refractiveindex.info/?shelf=main&book=Au&page=Johnson).
Coatings, size-dependent electron surface damping, aggregation, polydispersity
and changes in solvent are not included. In particular, small-particle spectra
are bulk-material approximations. These optical references do not calibrate
donor–gold quenching.

Extinction includes both absorption and scattering. Cross sections are in nm².
The decadic molar extinction coefficient is per mole of **particles**, not gold
atoms: `epsilon = Cext_nm2 * 1e-14 * NA / (1000 * ln(10))`, in M⁻¹ cm⁻¹.
Peak positions are grid maxima over the displayed spectral window.

The comparison table transcribes the nominal BioPure gold nanosphere diameter,
peak wavelength, peak OD/cm and particle concentration from
[nanoComposix standard product specifications](https://nanocomposix.com/pages/standard-product-specifications)
(accessed 2026-09-12). Its epsilon values are derived as
`OD_per_cm * NA / (1000 * particles_per_mL)`. The nearest vendor size is highlighted;
vendor values are not relabeled as measurements of an arbitrary entered size.
Differences between the vendor table and calculated curves are retained.
[Haiss et al. (2007)](https://doi.org/10.1021/ac0702084) provide relevant primary
research on size-dependent gold optical spectra and particle concentration.

Rebuild `backend/data/photophysics/gold_optics.json` with:

```sh
uv run --no-project --with miepython==3.0.2 --with pyyaml python scripts/build_gold_optics.py
```

The generator reads the bundled optical constants, so no download is required
once the Python dependencies are installed. Browser rendering requires no network
access to the reference sources. See `frontend/src/ui/gold_optics.js` for interpolation
and coefficient conversion and `gold_creation_dialog.js` for the popup.

Gold creation now omits coating controls. Streptavidin publication coverage and
count overrides are configured in Conjugate Manager → Streptavidin.
