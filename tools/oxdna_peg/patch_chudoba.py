"""Second-stage patch for the published PEG model, following patch_engine.py."""
from pathlib import Path


def patch(source: Path):
    math_header=source/'src/Interactions/chudoba_math.h'
    contents=(Path(__file__).parent/'chudoba_math.h').read_text()
    if not math_header.exists() or math_header.read_text()!=contents:
        math_header.write_text(contents)
    header = source/'src/Interactions/DNAInteraction.h' 
    if 'NADOC_CHUDOBA_V1' in header.read_text():
        return
    changes = {}

    def edit(name, old, new):
        text = changes.get(name, (source/name).read_text())
        if old not in text:
            raise RuntimeError(f'Missing Chudoba patch anchor: {name}: {old[:70]}')
        changes[name] = text.replace(old, new, 1)

    edit('src/Interactions/DNAInteraction.h', 'bool _peg_model = false;', '''bool _peg_model = false;
    // NADOC_CHUDOBA_V1
    bool _peg_chudoba = false;
    number _peg_chudoba_bonded(BaseParticle *p, BaseParticle *q, bool update_forces);''')
    cpp='src/Interactions/DNAInteraction.cpp'
    edit(cpp, '#include "DNAInteraction.h"', '#include "DNAInteraction.h"\n#include "chudoba_math.h"')
    edit(cpp, 'if(_peg_model) {\n        getInputNumber', '''if(_peg_model) {
        getInputBool(&inp, "peg_chudoba", &_peg_chudoba, 0);
        getInputNumber''')
    edit(cpp, 'OX_LOG(Logger::LOG_INFO, "NADOC_DNA2PEG_V1:', '''if(_peg_chudoba) {
            _peg_bond_length = .33/.8518;
            _peg_bond_k = 17000.*.8518*.8518/24.943387854;
            OX_LOG(Logger::LOG_INFO, "Chudoba 2017 PEG: one EO per bead, published implicit-water Hamiltonian");
        }
        OX_LOG(Logger::LOG_INFO, "NADOC_DNA2PEG_V1:''')
    edit(cpp, '_sqr_rcut = SQR(_rcut);', 'if(_peg_chudoba) _rcut = std::max(_rcut, .9/.8518);\n\t_sqr_rcut = SQR(_rcut);')
    edit(cpp, 'number DNAInteraction::_peg_spring(BaseParticle *p, BaseParticle *q, bool update_forces) {', '''number DNAInteraction::_peg_spring(BaseParticle *p, BaseParticle *q, bool update_forces) {
    if(_peg_chudoba) return _peg_chudoba_bonded(p,q,update_forces);''')
    edit(cpp, 'number DNAInteraction::_peg_repulsion(BaseParticle *p, BaseParticle *q, bool update_forces) {', '''number DNAInteraction::_peg_repulsion(BaseParticle *p, BaseParticle *q, bool update_forces) {
    if(_peg_chudoba && _peg_particle(p) && _peg_particle(q)) {
        number r = _computed_r.module(), derivative;
        if(r < 1.e-12) throw oxDNAException("Coincident Chudoba PEG beads");
        number energy = chudoba::pair(r*.8518, _T*3000., derivative)/24.943387854;
        if(update_forces) {
            LR_vector f = _computed_r*(derivative*.8518/(24.943387854*r));
            p->force += f; q->force -= f;
            _update_stress_tensor(p,q,_computed_r,-f);
        }
        return energy;
    }''')
    # A term is owned by its first bond. Every particle in that term must list
    # that owner bond in affected, so single-particle MC updates remain exact.
    edit(cpp, '*N_strands = parser.N_strands();', '''if(_peg_chudoba) {
        for(BaseParticle *p : particles) if(_peg_particle(p)) {
            BaseParticle *a=p;
            for(int back=0; back<4 && a!=P_VIRTUAL; ++back,a=a->n5) {
                if(a->n3==P_VIRTUAL) continue;
                BaseParticle *b=a->n3;
                bool found=false;
                for(auto &pair : p->affected) if((pair.first==a && pair.second==b)||(pair.first==b && pair.second==a)) found=true;
                if(!found) p->affected.push_back(ParticlePair(a,b));
            }
        }
    }
    *N_strands = parser.N_strands();''')
    changes[cpp] += '''
number DNAInteraction::_peg_chudoba_bonded(BaseParticle *p, BaseParticle *q, bool update_forces) {
    using V=chudoba::Vec<number>;
    BaseParticle *ps[4]={p,q,P_VIRTUAL,P_VIRTUAL};
    if(q->n3!=P_VIRTUAL) {ps[2]=q->n3;ps[3]=ps[2]->n3;}
    V u[3], f[4]; int count=2;
    if(ps[2]!=P_VIRTUAL) count=3;
    if(ps[3]!=P_VIRTUAL) count=4;
    for(int i=0;i<count-1;i++) {
        LR_vector r=ps[i+1]->pos-ps[i]->pos;
        u[i]=V(r.x*.8518,r.y*.8518,r.z*.8518);
        if(chudoba::dot(u[i],u[i])<1.e-20) throw oxDNAException("Zero PEG bond");
    }
    auto apply=[&](int n) {
        if(!update_forces) return;
        for(int i=0;i<n;i++) {
            LR_vector ff(f[i].x,f[i].y,f[i].z);
            ff *= .8518/24.943387854;
            ps[i]->force += ff;
            if(i) _update_stress_tensor(ps[i]->pos-p->pos,ff);
        }
    };
    number e=chudoba::bond(u[0],f);apply(2);
    if(count>=3) {e+=chudoba::angle(u[0],u[1],f);apply(3);}
    if(count==4) {
        auto a=chudoba::cross(u[0],u[1]),b=chudoba::cross(u[1],u[2]);
        if(chudoba::dot(a,a)*chudoba::dot(b,b)<1.e-30) throw oxDNAException("Collinear PEG dihedral");
        e+=chudoba::torsion(u[0],u[1],u[2],f);apply(4);
    }
    return e/24.943387854;
}
'''
    # Until the GPU force kernels are wired, reject the opt-in explicitly.
    edit('src/CUDA/Interactions/CUDADNAInteraction.cu', 'void CUDADNAInteraction::cuda_init(int N) {', '''void CUDADNAInteraction::cuda_init(int N) {
    if(_peg_chudoba) throw oxDNAException("Chudoba CUDA integration pending");''')
    for name, text in changes.items():
        (source/name).write_text(text)
    (source/'src/Interactions/chudoba_math.h').write_text((Path(__file__).parent/'chudoba_math.h').read_text())


if __name__ == '__main__':
    import sys
    patch(Path(sys.argv[1]))
