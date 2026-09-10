#pragma once
#include "MD_CUDAMixedBackend.h"
#include "../../Backends/MCMoves/MoleculeVolumeMove.h"

// Equilibrium sampler: GPU Verlet proposals with exact endpoint Metropolis
// correction. These macro steps are NOT physical MD time.
class PEGHMCBackend : public CUDAMixedBackend {
    int _peg_hmc_steps=100;
    int _peg_hmc_volume_attempts=0;
    llint _peg_hmc_attempted=0, _peg_hmc_accepted=0;
    std::shared_ptr<MoleculeVolumeMove> _peg_hmc_volume;
    void _peg_sync_forces();
public:
    void get_settings(input_file &inp) override;
    void init() override;
    void sim_step() override;
    void fix_diffusion() override {} // Do not constrain refreshed HMC momenta.
};
