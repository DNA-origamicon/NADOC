# Native GPU barostat compatibility audit

The native GPU MD barostat is **not enabled** in the PEG benchmark launchers.
Source snapshots are identified by hashes in
[the audit record](reference/native_gpu_barostat_audit.json).

The isotropic move proposes a symmetric increment in cubic side length L,
while its acceptance exponent includes N_objects log(V'/V). For the usual NPT
measure dV, dV/dL = 3L² contributes another (2/3) log(V'/V). Equivalently,
the proposal density in V is proportional to V'^(-2/3), giving that same
Hastings correction. The uncorrected ideal-system marginal is proportional to
V^(N_objects−2/3) exp(−βPV), whose mean is (N_objects+1/3)kT/P rather than
(N_objects+1)kT/P. Anisotropic box proposals require their own measure audit.

The molecular rescaling kernel updates the float position array. The mixed
backend's next integration step uses its double position array. It overrides
atomic rescaling to synchronize those arrays but has no equivalent molecular
rescaling override in the inspected source. This is a source-level concern;
no native-barostat PEG benchmark was launched to treat it as validated behavior.

The current CPU NPT and GPU HMC workflows use the separately tested molecular
log-volume move. Its Jacobian is N_molecules+1, and HMC explicitly synchronizes
positions and forces after volume attempts. The concerns above do not change
those workflows or the ongoing NVT GPU dynamics comparison.

A future native-barostat integration would need both corrections, complete PEG
GPU energy verification, ideal-volume distribution tests and interacting-system
CPU/GPU checks before production use. No engine changes were made in this audit.
