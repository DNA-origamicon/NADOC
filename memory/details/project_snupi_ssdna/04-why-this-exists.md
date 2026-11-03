# Why this exists — supporting detail

[Topic head](../../project_snupi_ssdna.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## Why this exists

Two motives, both from the user, and they pull in the same direction:

1. **Science.** VoltronCore is 12% ssDNA by nucleotide and we currently model 0% of it.
2. **Figures.** SNUPI's practical selling point is producing MD-looking pictures in minutes instead of
   weeks. A trajectory in which 55 overhangs sit rigidly frozen while the duplex core breathes does not
   look MD-simulated. Waving tails are not decoration — they are the thing that makes the figure read as
   a real simulation.

## What the SNUPI literature actually does (settled — do not re-research this)

SNUPI has a **first-class ssDNA finite element** — added in Lee JY, Kim M, Lee C, Kim D-N, *ACS Nano*
2021, 15(12), 20430–20441 ("Characterizing and Harnessing the Mechanical Properties of Short
Single-Stranded DNA in Structured Assemblies", [doi:10.1021/acsnano.1c08861](https://pubs.acs.org/doi/10.1021/acsnano.1c08861));
the SNUPI GitHub changelog marks **v2.00 = "Improved modeling of the single-stranded DNA"**. But that
element is strictly an **end-to-end connection between two base-pair nodes**. The 2023 dynamics paper
(*Nat Commun* 14:7079) enumerates exactly three connection types: bp steps, crossover steps, and
"end-to-end connection of single-stranded DNA."

Verified against the real install (`~/SNUPI`, compiled MCC binary — parameters in `~/SNUPI/Default.snp`
lines 88–153; FE model reverse-engineered from actual `NODE`/`PROP`/`E_CONN` run outputs):

- Nodes exist **only at base pairs**. `NODE` count == the count of staple-paired scaffold bases, exactly.
- Each contiguous unpaired scaffold run collapses to **exactly one 2-node beam**. Confirmed by bijection
  on two designs: `3x4SQ` has unpaired runs `[6,6,10,14,16,16,16,16,22,22,24]` → 11 ssDNA elements;
  `6hbx100_noT` has `[6,6,10,10,18,18]` → 6. The nt→length map is consistent across both designs.
- **Rest length is the WLC RMS end-to-end distance, NOT the contour**: 6 nt → 2.267 nm, 10 nt → 2.865 nm,
  18 nt → 3.669 nm, 24 nt → 4.147 nm (contour for 24 nt would be ~16 nm).
- ssDNA elements are the **only isotropic** ones in the whole model (`EIy == EIz` exactly) — every
  duplex/crossover element is anisotropic. A clean discriminator if you ever need to identify them.
- A **free tail has no second bp node to connect to**, so it contributes no element, no node, no mass, no
  drag. The words "overhang" and "toehold" appear **zero times** in SNUPI's docs, options file, or any
  shipped example. This is a structural limitation of the formulation, not an oversight.

Lineage: CanDo (Kim, Kilchherr, Dietz, Bathe, *NAR* 2012, [PMC3326316](https://pmc.ncbi.nlm.nih.gov/articles/PMC3326316/))
modeled ssDNA as a nonlinear modified-FJC entropic spring with **no bending or torsional stiffness**.
SNUPI's advance is promoting it to a full beam. The standing critique of bp-resolution FEM is exactly
that treating ssDNA as a zero-length connection over-stiffens origami — engineered ssDNA gaps drop
bending stiffness by up to 70% in experiment (*ACS Nano* 2019, [doi:10.1021/acsnano.9b03770](https://pubs.acs.org/doi/10.1021/acsnano.9b03770)).

### SNUPI ssDNA constants — the LAWS' INPUTS, not the element (source `~/SNUPI/Default.snp:88-153`)

⚠️ **Superseded as a build recipe by SS-1.** These are the published inputs; the closed forms that turn
them into `(L_rest, EA, EI, GJ)` are inside the compiled binary and are **not** any of the obvious WLC
combinations (all were 15–20 % off). The element is `snupi_material.ssdna_element(n)`, measured from the
binary itself. Keep this table for physical intuition and for the asymptotes it names
(`SS_GJ_L = 2`, `SS_EA_L = 15`, both confirmed in the measurement).

| Key | Value (mean ± std) | Meaning |
|---|---|---|
| `SS_LCT1_S` | 0.38 ± 0.11 nm/nt | contour length per nt, **short** ssDNA |
| `SS_LCT1_L` | 0.68 ± 0.29 nm/nt | contour length per nt, **long** ssDNA |
| `SS_LCT1_k` | 0.20 ± 0.02 | crossover coefficient short→long |
| `SS_LPB_L` | **0.67 ± 0.15 nm** | persistence length, long ssDNA |
| `SS_LPB_ka` / `SS_LPB_kb` | 5.4 ± 0.3 / 0.21 ± 0.02 | length-dependence coefficients for `L_p` |
| `SS_EA_L` / `SS_EA_H` | **15 ± 2.8 pN** / **710 ± 60 pN** | stretch rigidity, relaxed / taut |
| `SS_EA_ka/kb/kc` | 80 / 0.072 / 1.16 | nonlinear (extension-dependent) EA interpolation |
| `SS_GJ_H` / `SS_GJ_L` | 15 ± 3.6 / 2 ± 1.2 pN·nm² | torsional rigidity, short / long |

**The properties are length-dependent, and that is the physics.** A 2-nt gap is a stiff, near-taut,
pre-tensioned element (they measure ~12 pN of tension); a 20-nt loop relaxes to bulk-polymer floppiness
(`L_p` 0.67 nm, GJ 2 pN·nm²). Our current single `L_P_SS = 1.5 nm` constant captures neither end.

Observed in real runs, for cross-checking the transcription: `nt=6 → L=2.2667, GJ=6.937, EI=40.601,
EA=15.000`; `nt=10 → L=2.8647, GJ=4.039, EI=39.788`; `nt=16 → L=3.4908, GJ=2.549, EI=27.412`;
`nt=24 → L=4.1470, GJ=2.102, EI=14.240`. EA pins at `SS_EA_L=15` for relaxed runs; short/near-taut
runs stiffen (TALOS poly-T: `L=1.3198, EI=2.775, EA=116.4`).

## The three cases (the whole plan in one table)

| Case | Physics | SNUPI | NADOC now | Phase |
|---|---|---|---|---|
| ssDNA **bridging** two duplexes (interior gap, cross-helix hop, vertex linker) | load-bearing; softens the structure | one soft isotropic beam between the flanking bp nodes | ✅ **SNUPI's real element** (`material="snupi"`) — same beam, same measured properties | **SS-1 DONE** |
| ssDNA **free tail** (overhang, toehold, dangling scaffold end) | carries no load between duplexes; contributes mass, drag, excluded volume, and *visible thermal motion* | **cannot represent** — no distal node | invisible | **SS-2/3/4** |
| ssDNA **tail that binds a partner** (a connected overhang duplex) | already a duplex | n/a | already meshed as duplex (`connect_overhangs`) | — no work |
