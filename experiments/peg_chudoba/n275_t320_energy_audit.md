# N275, 320 K energy and pivot source audit

Nine saved configurations (steps 150000, 225000 and 300000 from each of the
three extension replicas) agree with the independent physical-unit, all-pairs
energy oracle. Maximum absolute error is 7.94e-13 oxDNA energy units per bead.
Each configuration's spatial extent is less than half the box along every axis,
so minimum-image wrapping does not change this comparison. The high-precision
trajectory energy field was used instead of the rounded energy log.

[Numerical evidence and oracle hash](n275_t320_energy_audit.json).

Source inspection found:

- `DNANucleotide::is_bonded` identifies only n3/n5 neighbors. The cell list
  excludes those direct neighbors, consistent with the preprint methods.
- The actual run log reports `IS_MC: 1`. Cell neighbor lists therefore include
  neighbors on both index sides, which the local pivot-energy sum requires.
- `ParticlePair` sorts its endpoints by index; sets of these pairs deduplicate
  interactions involving two moved particles.
- The PEG topology patch registers owner bonds for bonded terms involving each
  particle. Pivot energy gathers these owners across the moved segment.
- Trial positions update the cell list before evaluating trial energy. Rejected
  moves restore positions and update the list. The run logs show adaptation
  disabled (`adjust_moves=0`), so production proposals are not adapting.

These checks found no exclusion or endpoint-energy error. They do **not** prove
that every proposal's acceptance energy is correct: saved endpoint energies can
agree even when a sampler uses an incorrect trial energy difference. A direct
trial-energy audit or independent sampler comparison at N275/320 K remains the
next useful discriminator. No additional simulation was launched, and no force
or sampler implementation was changed. The existing serial queue remains active.

## Follow-up: offline trial accounting

Twelve deterministic rotations of the three saved final configurations were checked, covering both pivot directions, near-terminal and central pivots. Four proposals changed the set of pairs inside the cutoff. The local affected-owner energy difference agreed with the full-chain oracle to a maximum absolute difference of 7.28e-11 kJ/mol. This supports the mathematical accounting rule but does not test native cell-list updates or the native acceptance branch. The radius discrepancy remains unresolved.

Reproduce with `nice -n 19 python -m experiments.peg_chudoba.audit_pivot_accounting`. See [proposal results](pivot_accounting_audit.json) and [audit script](audit_pivot_accounting.py). No engine process was launched or rebuilt.
