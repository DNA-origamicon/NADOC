"""Exact molecular-volume proposals for PEG and local pivot energy sums."""
from pathlib import Path


def patch(source):
    pivot=source/'src/Backends/MCMoves/Pivot.cpp'
    text=pivot.read_text()
    if 'NADOC_PEG_LOCAL_PIVOT' not in text:
        text=text.replace('number delta_E = peg ? -system_energy() : 0.;','''// NADOC_PEG_LOCAL_PIVOT: count each changed term exactly once.
    auto peg_energy=[&]() {
        std::set<ParticlePair> bonded,nonbonded;
        for(int i=0;i<N_in_move;i++) {
            auto p=_Info->particles()[temp_particles[i].index];
            for(auto &pair:p->affected) bonded.insert(pair);
            for(auto q:_Info->lists->get_neigh_list(p)) nonbonded.insert(ParticlePair(p,q));
        }
        number e=0;
        for(auto &pair:bonded) e+=_Info->interaction->pair_interaction_bonded(pair.first,pair.second);
        for(auto &pair:nonbonded) e+=_Info->interaction->pair_interaction_nonbonded(pair.first,pair.second);
        return e;
    };
    number delta_E = peg ? -peg_energy() : 0.;''',1)
        text=text.replace('if(peg) delta_E += system_energy();','if(peg) delta_E += peg_energy();',1)
        pivot.write_text(text)
    text=pivot.read_text()
    if 'NADOC_PEG_PIVOT_LIST_REUSE' not in text:
        anchor='\t\t_Info->lists->global_update();\n\t}\n\telse {'
        assert anchor in text
        text=text.replace(anchor,'''        // NADOC_PEG_PIVOT_LIST_REUSE: single_update already maintains cells;
        // dirty Verlet lists were rebuilt before evaluating trial energy.
        if(!peg || !_Info->lists->is_updated()) _Info->lists->global_update();
    }
    else {''',1)
        pivot.write_text(text)
    volume=source/'src/Backends/MCMoves/MoleculeVolumeMove.cpp'
    text=volume.read_text()
    if 'NADOC_PEG_LOG_VOLUME' not in text:
        text=text.replace('int N_molecules = _Info->molecules().size();','''int N_molecules = _Info->molecules().size();
    bool peg=false; // NADOC_PEG_LOG_VOLUME
    for(auto p:particles) if(p->btype==500) {peg=true;break;}
    if(peg && !_isotropic) throw oxDNAException("PEG molecular volume sampling requires isotropic log-volume proposals");''',1)
        text=text.replace('if(_isotropic) {','''if(peg) {
        // A symmetric log(V) proposal matches the (N_molecules+1) Jacobian
        // in the Metropolis ratio below. Delta is dimensionless for PEG.
        number scale=exp(_delta*(drand48()-.5)/3.);
        box_sides*=scale;
    }
    else if(_isotropic) {''',1)
        text=text.replace('if(!_Info->lists->is_updated()) {','if(peg || !_Info->lists->is_updated()) {')
        volume.write_text(text)


if __name__=='__main__':
    import sys
    patch(Path(sys.argv[1]))
