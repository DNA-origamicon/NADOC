"""Many-body-aware MC total energy and CPU pressure for the PEG extension."""
from pathlib import Path


def patch(source):
    mc=source/'src/Backends/MC_CPUBackend.cpp'
    text=mc.read_text()
    if 'NADOC_PEG_MC_TOTAL' not in text:
        old='\t_U *= (number) 0.5;'
        assert old in text
        text=text.replace(old,old+'''
    // NADOC_PEG_MC_TOTAL: affected term ownership is not necessarily pairwise.
    for(auto p : _particles) if(p->btype==500) {
        _U=_interaction->get_system_energy(_particles,_lists.get());
        break;
    }''',1)
        mc.write_text(text)
    pivot=source/'src/Backends/MCMoves/Pivot.cpp'
    text=pivot.read_text()
    if 'NADOC_PEG_PIVOT' not in text:
        text=text.replace('number delta_E = 0.;', 'bool peg=pivot_p->btype==500; // NADOC_PEG_PIVOT\n\tnumber delta_E = peg ? -system_energy() : 0.;',1)
        text=text.replace('particle_energy(p) + p->ext_potential', '(peg ? 0. : particle_energy(p)) + p->ext_potential')
        text=text.replace('\t// accept or reject?', '\tif(peg) delta_E += system_energy();\n\t// accept or reject?',1)
        pivot.write_text(text)
    h=source/'src/Observables/Pressure.h' 
    text=h.read_text()
    if '_peg_recompute' not in text:
        h.write_text(text.replace('bool _PV_only;', 'bool _PV_only;\n    bool _peg_recompute = false;'))
        cpp=source/'src/Observables/Pressure.cpp'
        text=cpp.read_text()
        text=text.replace('BaseObservable::get_settings(my_inp, sim_inp);','''BaseObservable::get_settings(my_inp, sim_inp);
    bool peg=false;
    std::string backend;
    getInputBool(&sim_inp,"peg_chudoba",&peg,0);
    getInputString(&sim_inp,"backend",backend,0);
    _peg_recompute=peg && backend=="CPU";''',1)
        text=text.replace('std::string Pressure::get_output_string(llint curr_step) {','''std::string Pressure::get_output_string(llint curr_step) {
    if(_peg_recompute) {
        // Sample current positions and velocities, preserving integrator state.
        // Generic pair-force virials cannot represent angle/torsion terms.
        auto &particles=_config_info->particles();
        std::vector<LR_vector> force,torque;
        for(auto p:particles) {force.push_back(p->force);torque.push_back(p->torque);}
        _config_info->interaction->begin_energy_and_force_computation();
        for(auto &pair:_config_info->lists->get_potential_interactions())
            _config_info->interaction->pair_interaction(pair.first,pair.second,true,true);
        for(size_t i=0;i<particles.size();i++) {particles[i]->force=force[i];particles[i]->torque=torque[i];}
    }''',1)
        cpp.write_text(text)


if __name__=='__main__':
    import sys
    patch(Path(sys.argv[1]))
