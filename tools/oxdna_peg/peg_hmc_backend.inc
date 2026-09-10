// NADOC_PEG_HMC_V1
#include "PEGHMCBackend.h"

void PEGHMCBackend::get_settings(input_file &inp) {
    CUDAMixedBackend::get_settings(inp);
    bool chudoba=false,pure=false;
    getInputBool(&inp,"peg_chudoba",&chudoba,0);
    getInputBool(&inp,"peg_chudoba_pure",&pure,0);
    getInputInt(&inp,"peg_hmc_steps",&_peg_hmc_steps,0);
    getInputInt(&inp,"peg_hmc_volume_attempts",&_peg_hmc_volume_attempts,0);
    if(!chudoba || !pure || _peg_hmc_steps<1 || _peg_hmc_volume_attempts<0 || _external_forces || _use_barostat || _sort_every>0)
        throw oxDNAException("PEG_HMC requires pure Chudoba PEG, positive trajectory length, no external forces, sorting or MD barostat");
    if(_peg_hmc_volume_attempts) {
        number delta=.04;
        getInputNumber(&inp,"peg_hmc_volume_delta",&delta,0);
        if(delta<=0) throw oxDNAException("PEG HMC log-volume delta must be positive");
        auto settings=Utils::get_input_file_from_string(Utils::sformat("type = molecule_volume\ndelta = %.16g\nprob = 1\n",delta));
        _peg_hmc_volume=std::make_shared<MoleculeVolumeMove>();
        _peg_hmc_volume->get_settings(*settings,inp);
        delete settings;
    }
}

void PEGHMCBackend::init() {
    CUDAMixedBackend::init();
    for(auto p:_particles) if(p->btype!=500) throw oxDNAException("PEG_HMC only supports chemical PEG beads");
    if(_peg_hmc_volume) _peg_hmc_volume->init();
    OX_LOG(Logger::LOG_INFO,"PEG_HMC: %d GPU Verlet steps per equilibrium proposal; macro steps have no physical time mapping",_peg_hmc_steps);
}

void PEGHMCBackend::_peg_sync_forces() {
    auto sides=_box->box_sides();
    _h_cuda_box.change_sides(sides.x,sides.y,sides.z);
    CUDA_SAFE_CALL(cudaMemcpy(_d_cuda_box,&_h_cuda_box,sizeof(CUDABox),cudaMemcpyHostToDevice));
    apply_changes_to_simulation_data();
    _cuda_lists->update(_d_poss,_d_list_poss,_d_bonds);
    _d_are_lists_old[0]=false;
    _set_external_forces();
    _cuda_interaction->compute_forces(_cuda_lists,_d_poss,_d_orientations,_d_forces,_d_torques,_d_bonds,_d_cuda_box);
}

void PEGHMCBackend::sim_step() {
    _mytimer->resume();
    apply_simulation_data_changes();
    std::vector<LR_vector> old_positions(N()),old_velocities(N());
    number old_h=_interaction->get_system_energy(_particles,_lists.get());
    number root_t=sqrt(_T);
    for(int i=0;i<N();i++) {
        auto p=_particles[i];old_positions[i]=p->pos;
        p->vel=LR_vector(Utils::gaussian(),Utils::gaussian(),Utils::gaussian())*root_t;
        old_velocities[i]=p->vel;
        old_h+=p->vel.norm()/2.;
    }
    _peg_sync_forces();
    for(int step=0;step<_peg_hmc_steps;step++) {
        _first_step();
        if(_d_are_lists_old[0]) {
            _cuda_lists->update(_d_poss,_d_list_poss,_d_bonds);
            _d_are_lists_old[0]=false;
            _N_updates++;
        }
        _forces_second_step();
    }
    apply_simulation_data_changes();
    number new_h=_interaction->get_system_energy(_particles,_lists.get());
    for(auto p:_particles) new_h+=p->vel.norm()/2.;
    number delta_h=new_h-old_h;
    bool accepted=std::isfinite(new_h) && log(drand48()) < -delta_h/_T;
    _peg_hmc_attempted++;
    if(accepted) _peg_hmc_accepted++;
    else {
        for(int i=0;i<N();i++) {
            auto p=_particles[i];p->pos=old_positions[i];p->vel=old_velocities[i];p->set_positions();
        }
        _interaction->set_is_infinite(false);
        _lists->global_update(true);
    }
    // Momentum reversal makes the deterministic proposal an involution.
    // Momenta are independently refreshed at the next macro step.
    for(auto p:_particles) p->vel=-p->vel;
    for(int i=0;i<_peg_hmc_volume_attempts;i++) _peg_hmc_volume->apply(current_step());
    _peg_sync_forces();
    _backend_info=Utils::sformat(" HMC_accept=%.6g HMC_deltaH=%.12g HMC_accepted=%d",double(_peg_hmc_accepted)/_peg_hmc_attempted,delta_h,int(accepted));
    _mytimer->pause();
}
