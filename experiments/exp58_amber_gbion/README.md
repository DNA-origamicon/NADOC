# exp58 — native Amber26 OL15/GBION validation

Final status: **closed for production use.** The campaign is negative for raw
origami-scale throughput and inconclusive for effective curved-origami equilibration.
Do not repeat the exp58 protocol as-is. See
[`FINAL_ASSESSMENT.md`](FINAL_ASSESSMENT.md) for the final decision, protocol audit,
and explicit conditions for any future reconsideration.

The native Amber26 RunPod duplex gate passed on 2026-08-27. See
[`RESULTS.md`](RESULTS.md) for the measured result and its limits.

Origami status: **a relaxed 656-nt 6HB remained stable for 0.1 ns but failed the
production-performance objective.** It ran at 18.28 ns/day on a 4090 versus 90.90
ns/day for the archived explicit NAMD run on a 3080 Ti. See
[`RESULTS_6HB.md`](RESULTS_6HB.md).

Important final-audit limitation: the run measured nominal throughput, not wall time
to convergence of a curved-origami observable. It also used `gamma_ln=1.0 ps^-1`,
anion-related GBION coefficients of 10, and `gbsa=3`; the published GBION DNA protocol
used low-friction `0.05 ps^-1`, coefficients of 8, and normally `gbsa=0`. The archived
result remains valid for its exact input but is not a test of the published
accelerated-sampling regime.

## Scientific model

- Amber26 `pmemd.cuda`
- OL15 DNA
- GBneck2 (`igb=8`) with GBION v3 (`gbion=3`)
- explicit Na+/Cl- at a nominal 0.150 M, counted with Amber's SLTCAP equation
- Joung/Cheatham TIP3P ion parameters, `mbondi3`, and a 1.4 A chloride GB radius
- no Debye screening (`saltcon=0`) and no ALPB (`alpb=0`)
- a 40 A flat-bottom spherical restraint on ions, centered on the DNA phosphorus COM
- 300 K Langevin dynamics, 2 fs, SHAKE on X-H bonds, no HMR

OL15 is the solute force field and GBION is the solvent/ion model. They are not
alternative choices; this is the combination parameterized and recommended by Amber.

## First paid gate

1. Verify the Amber source checksum, absence of another exp58-owned pod, confirmation
   queue, and cumulative campaign ledger before pod creation. Unrelated pods are allowed.
2. Build/test the licensed Amber26 CUDA executable once on the pod.
3. Build a 21-bp duplex with AmberTools26 and confirm exact net charge and ion counts.
4. Confirm `pmemd.cuda` accepts the complete `igb=8`, `gbion=3`, `gbsa=3`, and
   `nmropt=1` input without CPU fallback.
5. Minimize, equilibrate, run a clean timing block, and sample at least 1 ns.
6. Gate Watson-Crick occupancy, C1' RMSD, finite energy, bond integrity, and ns/day.
7. Download all evidence, terminate the pod, independently prove that it is absent from
   the account, and close the spend ledger. Unrelated named pods are preserved and do
   not count against exp58's isolated ledger.

The hard aggregate budget is $5, including provisioning, compilation, failed launches,
and teardown. The controller reserves $0.25 for teardown and uses provider-owned
`terminateAfter` in addition to its own spend check.

## Licensed artifact

Download Amber26 for the licensed organization from
<https://ambermd.org/GetAmber.php>. For qualifying noncommercial work the fee is $0,
but accepting the license cannot be delegated to this automation. Place the resulting
file at a stable local path and run:

```bash
NADOC_AMBER26_TARBALL=/absolute/path/pmemd26.tar.bz2 \
  .venv/bin/python experiments/exp58_amber_gbion/preflight.py
```

The downloaded archive is expected to be exactly 349,473,241 bytes, with Amber's
published MD5 `ceeabc133e772c115183d5cf6a87676b` and the locally recorded SHA-256
`0478ccce892f3525e995e9c85458d552c6060b73dd28acd03c366e61ecf23a14`.
The preflight performs no molecular dynamics and creates no pod.

The paid launcher installs the AmberTools26 conda-forge build, builds the authenticated
licensed source with CUDA 12.8, and then runs the validation. The portable Amber CUDA
build is deliberately serial: each precision mode is compiled for eight GPU
architectures, and the follow-up 6HB run showed that even four concurrent jobs can
exceed 251 GiB when the two coarse-grid translation units overlap.

For the 6HB gate, Amber26's default CUDA 12.8 build still exceeded 251 GiB when two
coarse-grid units overlapped. `amber26_cuda_sm89.patch` makes the 6HB launcher build an
explicitly SM8.9-only binary for its allowed RTX 4090/RTX 6000 Ada candidates. That
artifact must not be presented as portable to other GPU architectures.

```bash
NADOC_AMBER26_TARBALL=/home/jojo/Downloads/pmemd26.tar.bz2 \
  .venv/bin/python experiments/exp58_amber_gbion/runpod.py
```

The test includes a one-cycle native `pmemd`/`pmemd.cuda` GBION energy comparison and
a same-GPU `pmemd.cuda` OL15/TIP3P benchmark. This prevents a raw ns/day number from
being misreported as either CUDA proof or an engine-controlled speedup.

NADOC's NAMD/CHARMM PDB export contains a phosphate on each 5' terminus. The Amber
worker converts these to standard unphosphorylated OL15 5' termini, retains strand
`TER` records, and rejects any topology containing an inter-strand covalent bond.

The raw `6hb_2xT` CAD geometry is not a valid direct dynamics seed: it contains 105
sub-0.8-A heavy-atom overlaps. The 6HB worker therefore requires the archived relaxed
NAMD reseed coordinates, maps all heavy atoms into the Amber terminal representation,
and rejects any initial Amber bond outside 0.8-2.0 A before parity or dynamics.
