# Reusing published PEG models in oxDNA

Assessment: 9 September 2026. **Port an existing implicit-solvent PEG model
before commissioning bulk atomistic parameterization.** The earlier
[validation budget](peg_validation_plan.md) overstates the necessary starting
work: its NAMD pilot and full campaign are optional allocations for new
calibration, not prerequisites for importing published PEG parameters.

## Preferred parameter source

Chudoba, Heyda and Dzubiella, *JCTC* **13**, 6317–6327 (2017),
[DOI: 10.1021/acs.jctc.7b00560](https://doi.org/10.1021/acs.jctc.7b00560),
provides an implicit-water Hamiltonian. Numerical values were checked in
[the open manuscript, Tables 1–2 and equations 1 and 12](https://arxiv.org/html/1710.09191v1).
The publisher also provides supporting information. Reference inventory:

| Term | Published parameters, physical units |
| --- | --- |
| Mapping | Neutral bead per symmetric CH2–O–CH2 group; methyl-capped termini |
| Bond | b0 = 0.33 nm; kb = 17,000 kJ mol⁻¹ nm⁻²; U = kb(b−b0)²/2 |
| Angle | θ0 = 130°; kθ = 85 kJ/mol; U = kθ(cos θ−cos θ0)²/2 |
| Torsions | Σ kn[1+cos(nφ−φn)]; n = 1,2,3,4; kn = 1.96,0.18,0.33,0.12 kJ/mol; φn = 180°,0°,0°,0° |
| Nonbonded | Normalized Mie plus Gaussian barrier, equation 12 |
| Mie | n = 8; m = 54 × 0.9943^(T/K); σ = [0.367 + 0.000139(T/K)] nm; corrected ε = 1.372 kJ/mol |
| Gaussian | γ = 0.4841 kJ/mol; μ = [0.604 + 0.00029(T/K)] nm; δ = 0.1064 nm |
| Conventions | Exclude only directly bonded neighbors; final cutoff 0.9 nm |

The paper benchmarks chain dimensions and osmotic pressure. Preserve the
corrected potential, rather than the intermediate ε′ = 1.193 kJ/mol fit.

## Other reusable assets

* **Existing oxDNA crowders:** Hong, Schreck and Šulc (2020),
  [DOI: 10.1093/nar/gkaa854](https://doi.org/10.1093/nar/gkaa854), has an
  [author repository](https://github.com/sulcgroup/crowderoxdna).
  [CrowderDNA2Interaction.cpp](https://github.com/sulcgroup/crowderoxdna/blob/342237df3326cb55e98ad70bc50658020b7456f8/src/Interactions/CrowderDNA2Interaction.cpp)
  implements repulsion against separate DNA backbone/base sites. This is a
  reusable steric-contact baseline, not a connected PEG force field or a
  calibration of PEG–DNA chemical affinity. GPU compatibility with our current
  engine has not been established; inspect and port deliberately.
* **Downloadable MARTINI PEO:** Grünewald et al. (2018),
  [DOI: 10.1021/acs.jpcb.8b04760](https://doi.org/10.1021/acs.jpcb.8b04760).
  Polyply supplies actual [MARTINI 2 PEO topology parameters](https://github.com/marrink-lab/polyply_1.0/blob/38d4d5424e1ef35c86e7cb8532fbd86ecf997221/polyply/data/martini2/PEO.martini.2.itp)
  and a separate [MARTINI 3 PEO definition](https://github.com/marrink-lab/polyply_1.0/blob/38d4d5424e1ef35c86e7cb8532fbd86ecf997221/polyply/data/martini3/PEO.martini3.ff).
  These require their corresponding solvent and force-field interactions.
  Removing explicit CG water and retaining the same PEG parameters does not
  establish an implicit-solvent oxDNA model. Useful for independent reference
  simulations; do not mix MARTINI versions or cherry-pick constants.
* **Simpler implicit model:** Xie et al. (2016),
  [DOI: 10.1016/j.polymer.2015.12.034](https://doi.org/10.1016/j.polymer.2015.12.034),
  offers a two-parameter hard-sphere chain model at room temperature. Its
  numerical parameter table was not verified in this assessment, so it is a
  secondary candidate rather than the selected import source.

## Work we still need

The present NADOC model uses 0.7 nm statistical segments, harmonic springs and
WCA repulsion. It is not an implementation of the preferred paper. Reusing
published parameters requires chemical-repeat mapping, angle/torsion forces,
the solvent-mediated pair potential, and CPU/CUDA consistency. Existing graft,
serialization, trajectory and GPU infrastructure remains useful. This is a
bounded force-field port, not simply replacing the current spring constant.

For the port, audit unit conversions, end groups, exclusions, cutoff/shift
conventions, masses, friction and integration stability. Start at a fixed
reference temperature. A variable-temperature Mie implementation must handle
the n = m limit robustly. Check the final publication/SI against the open
manuscript before freezing the implementation specification.

Recommended sequence:

1. Implement the complete published PEG-only Hamiltonian and check analytical
   forces, finite differences, energy accounting and CPU/CUDA agreement.
2. Reproduce reference chain-size and solution-pressure results at matching
   conditions, using independent seeds and autocorrelation-aware errors.
   Use published data as the target; no new atomistic simulations are required
   merely to reproduce an inherited bulk model. Do not infer physical kinetics
   from equilibrium agreement.
3. Add grafting and a documented DNA steric baseline. Check finite-size effects,
   brush-height distributions and limiting polymer-statistics behavior.
4. Commission targeted atomistic or experimental comparisons only for the
   remaining claims: substrate/linker affinity, PEG–DNA contacts, electrolyte
   dependence, and field-induced response. Bulk neutral-bead parameters alone
   cannot establish electrode polarization, ion redistribution or neutral PEG
   actuation. Nor does adding a terminal qE force validate those effects.

The previous 39–104 GPU-day NAMD estimate is therefore **not the entry cost**.
Keep its measured throughput and optional campaign arithmetic, but select new
simulations only after the specific remaining interaction is defined. No new
benchmark or cloud expenditure was necessary for this reassessment ($0 spent).
