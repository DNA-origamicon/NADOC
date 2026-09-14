# Gold nanoparticle quenching

The **FRET Checker** now applies continuous gold-quenching attenuation to supported
donors. Fluorescence alone remains the reference emission view. The scene's
**Gold quenching — Details** button lists donor/acceptor distances, estimates,
unsupported pairs, imported measurements and sources. All data are bundled;
viewing a design does not require a network connection.

## Imported experimental evidence

[Breshike, Riskowski & Strouse (2013)](https://doi.org/10.1021/jp407259r)
report size-dependent NSET. Numerical experimental characteristic distances are
available in [Breshike's thesis, Table 3.4, printed p. 67](https://www.chem.fsu.edu/~strouse/Theses_StrouseLab/BreshikeThesis.pdf#page=85).
We transcribed eleven FAM/Cy3B measurements, converting gold radius in nm to
diameter and characteristic distance in Å to nm. FAM d₀ increases from 7.25 nm
at 1.89 nm gold diameter to 32.08 nm at 16.5 nm diameter. Reference quantum
yields are 0.8 for FAM and 0.7 for Cy3B. Cy3B is not Cy3. Larger-particle
linker orientation adds uncertainty; these are reference estimates for a
specific experimental system, not calibrations of every NADOC sample.

[Jennings, Singh & Strouse (2006)](https://doi.org/10.1021/ja0583665)
provide lifetime evidence for inverse-fourth-power donor-to-surface transfer
near 1.5 nm gold. This supports distinguishing NSET from conventional FRET.

For QDs, [Li et al. (2011)](https://doi.org/10.1021/jz201002g) found an
inverse-fourth-power dependence with 3 nm gold and inverse-sixth-power dependence
with 15 and 80 nm gold. Spectral overlap and plasmon response matter. We imported
these size/law findings as evidence, not fitted radii.

[Samanta et al. (2014)](https://doi.org/10.1021/nl501709s) reported 30 nm gold,
approximately 28 nm half-quenching distance, exponent 2.7, and separations
15–70 nm. These numbers are imported as evidence only: the accessible abstract
does not establish the donor identity and geometric distance convention needed
to use its curve in the scene. Substituting this value for a vendor QD's
Förster radius would be unjustified.

[Ko, Du & Liddle (2013), author manuscript](https://tsapps.nist.gov/publication/get_pdf.cfm?pub_id=911962)
studied streptavidin-coated CdSe/ZnS Qdot 585/605 with 10, 15 and 20 nm gold on
DNA origami. Size, spacing, arrangement and spectral overlap affect lifetime and
photon count rate. Gold coupling can involve enhancement as well as quenching;
a universal monotonic radius rule cannot describe all such systems.

## Rendering and limits

Data: `backend/data/photophysics/gold_quenching.json`. Calculation:
`frontend/src/scene/gold_quenching.js`.

For a supported pair, normalized added decay rate is `k = (d0 / d)^4`, where
`d = distance(donor center, gold center) - gold diameter / 2`. The QD emitter
would be at its center, not its outer shell. Scene units are nm. Pair transfer
efficiency is `E = 1 - 1/(1+k)`. Half-distance means **50%**, not total extinction;
the curve continues beyond that distance. Independent gold rates add, giving
relative donor brightness `1/(1 + sum(k))`. This is an independent-acceptor
approximation; it does not solve collective electromagnetic coupling.

Within the measured gold-size range, d₀ is linearly interpolated, explicitly
labeled in Details. Outside that range, a pair is unknown. Applying the fitted
distance curve to an arbitrary separation is itself an estimate; the data do
not validate all distances. Contact/overlap is outside the model and reported
unknown. No chemical-contact quenching or plasmonic enhancement is synthesized.
The pre-existing dye–dye FRET size cue remains separate from gold attenuation.

Live nanoparticle transforms take precedence over saved poses, including preview
movement. Undo, redo, resizing, deletion and toggles refresh results. Hidden gold
still participates because hiding is a view operation. Neither calculation nor
the diagnostics change the design or feature log. Each glow and QD owns its
material so attenuation cannot bleed to another donor of the same color.

**Current vendor QDs are not quantitatively calibrated for gold quenching.**
Their catalog contains original spectrum plots and size ranges, but no matched
gold size/donor/coating/distance calibration. Their reference brightness is
retained and explicitly labeled unknown, never interpreted as zero quenching.
The same rule applies to unsupported dyes or gold sizes. If some acceptors are
supported and some unknown, only the supported rates attenuate the donor and
the donor is still marked uncalibrated overall.

To enable quantitative QD attenuation, obtain a donor-specific measured curve
with gold diameter, coating/environment, distance convention, validity range,
and fitted characteristic distance/exponent; or numerical spectra, quantum
yield and gold optical response for a separately validated electromagnetic
model. Matching only emission color, peak wavelength or semiconductor family
is insufficient. Functionalized QD import remains deferred.

Streptavidin-coated gold pairs are reported as uncalibrated rather than evaluated
with the bare-gold distance curve; protein/linker spacing and modified surface
chemistry require separate calibration.
