# Cis-anti CPD: first bounded torsion fit and updated NAMD checks

The user's instruction to continue toward NAMD readiness authorized this work.
The original v2 policy, failed QM/geometry results and two-round fitting budget
are unchanged. One conformational fitting round is now used; the second remains
unused. No additional QM, prospective validation, cloud work or app integration
was performed.

**The updated 62-atom two-nucleoside candidate is NAMD-tested.** The complete
3,043-atom DNA topology also passes a native static energy/force comparison.
Full-DNA dynamics remains blocked by failed coordinate construction.

Subsequent [solvent/control construction and source audit](cpd_anti_solvated_construction_20260926.md)
also failed at a shared unmodified sugar inversion. It identifies a separate
opposite-handed source C3′ at D002:26. Earlier source-sugar preservation results
below are relative to that source, not proof of chemically correct sugar chirality
throughout the DNA. The fragment QM-reference checks are unaffected.

The [engineering bundle](../.development-artifacts/cpd-anti-namd-engineering-bundle-v2-r1/README.md)
contains the exact tested fragment inputs and a separate full-DNA run-0 fixture.
The latter is explicitly not a dynamics release.

## Frozen method and evidence

`cpd-anti-conformational-inputs-v2/receipt.json` and the immutable conformational
stage lock were written before fitting. All 19 previously declared, exposed QM
cases remain, using endpoint-1 original and endpoint-2 lower-reference conformer
identities as common QM/MM energy references. None was energy-pruned.

Four ordered attachment proper torsions were selected: O4′–C1′–N1–C2 and
C2′–C1′–N1–C6 for each endpoint. Their n=1,2,3 signed cosine coefficient changes
were bounded to ±5 kcal/mol and exported with phases 0°/180°. Charges, LJ,
bond/angle/improper and all other proper terms remained fixed. The objective was
mean squared relative-energy error plus 0.05 times mean squared coefficient
change normalized by 3 kcal/mol. Two changes reached their bounds.

The fit follows the staged relaxed-MM-baseline/Fourier approach documented by
[ffTK](https://www.ks.uiuc.edu/Research/vmd/plugins/fftk/), associated with
[Mayne et al. (2013)](https://doi.org/10.1002/jcc.23422). This implementation uses
Sella/OpenMM and a bounded linear solve; it does not claim to invoke ffTK itself.
The coefficient bounds, regularization and finite budgets are local choices,
not literature certificates.

Baseline and post-fit MM relaxations each started separately from every QM
geometry. Scan/reference glycosidic angles were held at their measured QM values;
the remote unconstrained case remained free. Independent Cartesian force checks
and geometry checks were required, with at most 400 steps/600 evaluations per
case and two hours for the round. Every one of the 38 relaxations passed the
stationarity/chemistry checks. No MM scan Hessian/minimum claim follows.

## Results under the retained limits

| Check | Result | Status |
|---|---|---|
| 19-case relaxed energies | RMS 2.1952 → **0.5421** kcal/mol; maximum 7.0071 → **1.0099** kcal/mol | Pass 1/2 kcal/mol limits; exposed regression only |
| Core representative | Maximum lesion/attachment bond error 0.02057 Å, angle error 2.1764° | Pass 0.03 Å / 3° |
| Endpoint-1 representative | 0.02588 Å, 2.6047° | Pass |
| Remote endpoint-2 representative | 0.02306 Å, 2.2684° | Pass |
| Profile geometry descriptors | 12/19 meet inherited 0.25 Å heavy RMSD / 20° heavy-proper descriptors | Seven mismatches retained; qualification incomplete |
| Export replay | Maximum relative-energy discrepancy 5.7e−14 kcal/mol; force discrepancy 1.4e−14 kcal/mol/Å | Pass |
| Five MM engineering fixtures | Stationary, positive internal curvature at both finite-difference steps, stereo and bonds preserved | Pass local engineering stability |
| Ten native NAMD comparisons | Maximum energy discrepancy 0.0005581 kcal/mol, force 0.0007097 kcal/mol/Å | Pass |
| Updated 62-atom NAMD smoke | 100 ps, 300 K, 1 fs, ordinary masses; 101 frames plus final coordinates | All four lesion and six sugar stereocenters preserved |
| Full-DNA transfer | Exactly four attachment proper keys changed; all other forces and particles unchanged | Pass; parent sugar/phosphate retained |
| Full-DNA static NAMD | Energy discrepancy 0.00550 kcal/mol; force 0.00640 kcal/mol/Å | Pass original absolute-or-relative policy; no dynamics |

The full-DNA native tolerance is max(absolute limit, 1e−4 times the reference
magnitude). Its energy/force limits here were 5.5326 kcal/mol and
0.04945 kcal/mol/Å. The measured discrepancies are much smaller; they do not pass
the small-fragment absolute limits alone. The reference total energy is large
for this charged, unsolvated, nonstationary construction.

![QM and relaxed MM energies](../.development-artifacts/cpd-anti-conformational-fit-v2-r1/energy_profiles.png)

An independent replay reconstructed all 19 energies and gradients from the
exported CHARMM parameters, verified the final evaluated coordinates, repeated
the tangent-force projections at three finite-difference steps, and preserved all
case/reference identities. The four original/lower same-angle pairs remain
distinct after MM relaxation. Their largest shape mismatch is the lower +15°
point: heavy RMSD 0.6885 Å and maximum heavy-proper difference 40.10°, involving
N1/base-attachment geometry. Its original-minus-lower energy gap is 1.5956 kcal/mol
versus QM 1.4197. Good energy agreement does not resolve that geometry mismatch.

No second fit was run to lower already-passing energy errors. No candidate was
registered for the four prospective ±22.5° QM targets. Conformational scientific
qualification and preliminary context simulations remain incomplete.

## Full-DNA construction: finite failure retained

`cpd-anti-fitted-conditioning-v2` used the new fitted potential, the last valid
geometry from the failed source-conditioning attempt, and the same 514 mobile /
2,529 fixed atoms. A versioned method change used SLSQP with analytic signed-volume
derivatives instead of the previous trust-constr optimizer: at most 1,000
chirality-constrained iterations, then at most 1,500 unconstrained L-BFGS
iterations only if the first phase passed. Overall limits were 6,000 energy
evaluations/two hours/zero continuations. Earlier failures remain unchanged.

The first phase reached its **1,000-iteration cap** after 1,005 evaluations and
about 26 seconds. Maximum mobile force under the new potential fell from
25.4001 to **1.36065 kcal/mol/Å**, still above 0.01. All 288 source sugar and ten
local QM stereocenters were preserved; fixed coordinates were identical; bonds
remained within 0.8012–1.0797 of equilibrium; no severe contacts or saved-checkpoint
ring piercings were detected. The temporary chirality constraints were not removed.
Minimum oriented volume was 7.932 Å³, well away from the artificial 0.1 Å³ bound.

Maximum lesion base displacement grew to **14.0515 Å**, failing the retained
3.5 Å product screen. This is not a usable full-DNA dynamics starting model.
The terminal failure and all checkpoints are retained; no extension or dynamics
followed. Double-precision force replay confirms the failure. CPU-platform
energy differences were noisy at a 1e−4 Å displacement, despite agreement of
analytical CPU/Reference gradients within 4.8e−4 kcal/mol/Å at the seed; the
Reference finite-difference check passed. This numerical limitation is recorded,
not used to waive the force criterion.

The [shared-frame A/B](../.development-artifacts/cpd-anti-fitted-conditioning-v2/review.html)
and [static comparison](../.development-artifacts/cpd-anti-fitted-conditioning-v2/comparison.png)
show the source and failed candidate with per-endpoint glycosidic lengths.
The static rendering was visually inspected. The standalone interactive viewer
was generated but not browser-interaction tested. No saved design was changed.

The next construction-method review must address the substantial deformation in
this unsolvated, charged, fixed-boundary model before choosing another bounded
calculation. Repeating the same optimizer with a larger cap is not the selected
next step. The torsion-energy fit has its own successful result; it is not a reason
to relabel the DNA construction or seven profile geometry mismatches as passed.

## Retained records

- `cpd-anti-conformational-fit-v2-r1`: raw baseline/candidate evaluations, fit,
  export checks, independent replay, representative minima and energy figure.
- `cpd-anti-conformational-native-v2-r1`: ten native comparisons, 100 ps trajectory,
  original-QM stereochemistry audit and hash-pinned plan.
- `cpd-anti-fitted-dna-v2-r1`: exact coefficient-transfer audit, native parent terms,
  full-DNA PSF/parameters and static NAMD outputs.
- `cpd-anti-fitted-conditioning-v2`: failed bounded construction, independent
  replay, checkpoints and shared-frame review.
- Four focused regression tests passed in 1.04 s. Native preflights and export
  checks ran separately. No backend/frontend application behavior changed.

All jobs are terminal. Watcher queue acceptance is separate from receipt of a
completion wake; acknowledge tokens only when the actual wake is received.
The conformational wake was received/acknowledged at21:07:54UTC on2026-09-26;
its38 relaxations/1323 evaluations were rechecked. The subsequent read-only
[construction-method review](cpd_anti_construction_method_review_20260926.md)
selects a solvent/context preparation review before another bounded attempt.
