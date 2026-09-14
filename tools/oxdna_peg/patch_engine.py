"""Apply the opt-in DNA2PEG interaction to a clean pinned oxDNA checkout.

No production DNA2 behavior changes: all branches require DNA2PEG and base 500.
The marker fits oxDNA CUDA's signed ten-bit particle-type encoding.
"""
from pathlib import Path
import sys

MARKER = "NADOC_DNA2PEG_V1"


def patch(source: Path):
    if MARKER in (source / "src/Interactions/DNAInteraction.h").read_text():
        return
    changes = {}

    def edit(name, old, new, count=1):
        text = changes.get(name, (source / name).read_text())
        if text.count(old) < count:
            raise RuntimeError(f"oxDNA patch anchor missing: {name}: {old[:80]}")
        changes[name] = text.replace(old, new, count)

    header = "src/Interactions/DNAInteraction.h"
    edit(header, "protected:\n", "protected:\n" + r'''
    // NADOC_DNA2PEG_V1: neutral CM bead-spring chains, opt-in only.
    bool _peg_model = false;
    number _peg_bond_length = 0.821789;
    number _peg_bond_k = 100.;
    number _peg_sigma = 0.586992;
    number _peg_dna_sigma = 0.880488;
    number _peg_epsilon = 0.1;
    bool _peg_particle(BaseParticle *p) const {
        return p != P_VIRTUAL && p->btype == 500;
    }
    bool _peg_pair(BaseParticle *p, BaseParticle *q) const {
        return _peg_model && (_peg_particle(p) || _peg_particle(q));
    }
    number _peg_spring(BaseParticle *p, BaseParticle *q, bool update_forces);
    number _peg_repulsion(BaseParticle *p, BaseParticle *q, bool update_forces);
''')
    cpp = "src/Interactions/DNAInteraction.cpp"
    edit(cpp, "void DNAInteraction::get_settings(input_file &inp) {", "void DNAInteraction::get_settings(input_file &inp) {" + r'''
    std::string peg_interaction;
    getInputString(&inp, "interaction_type", peg_interaction, 0);
    _peg_model = peg_interaction == "DNA2PEG";
    if(_peg_model) {
        getInputNumber(&inp, "peg_bond_length", &_peg_bond_length, 1);
        getInputNumber(&inp, "peg_bond_k", &_peg_bond_k, 1);
        getInputNumber(&inp, "peg_sigma", &_peg_sigma, 1);
        getInputNumber(&inp, "peg_dna_sigma", &_peg_dna_sigma, 1);
        getInputNumber(&inp, "peg_epsilon", &_peg_epsilon, 1);
        if(!std::isfinite(_peg_bond_length) || _peg_bond_length <= 0 ||
           !std::isfinite(_peg_bond_k) || _peg_bond_k <= 0 ||
           !std::isfinite(_peg_sigma) || _peg_sigma <= 0 ||
           !std::isfinite(_peg_dna_sigma) || _peg_dna_sigma <= 0 ||
           !std::isfinite(_peg_epsilon) || _peg_epsilon < 0)
            throw oxDNAException("Invalid DNA2PEG parameters");
        OX_LOG(Logger::LOG_INFO, "NADOC_DNA2PEG_V1: neutral CM springs and WCA sterics; type 500");
    }
''')
    # The largest steric cutoff must be reflected in the shared neighbour list.
    edit(cpp, "_sqr_rcut = SQR(_rcut);", "if(_peg_model) _rcut = std::max(_rcut, std::pow(2., 1./6.) * std::max(_peg_sigma, _peg_dna_sigma));\n\t_sqr_rcut = SQR(_rcut);")
    signature = "number DNAInteraction::_backbone(BaseParticle *p, BaseParticle *q, bool compute_r, bool update_forces) {"
    edit(cpp, signature, signature + r'''
    if(_peg_pair(p, q)) {
        if(!_check_bonded_neighbour(&p, &q, compute_r)) return 0.;
        if(compute_r) _computed_r = q->pos - p->pos;
        return _peg_spring(p, q, update_forces);
    }
''')
    for term in ["_bonded_excluded_volume", "_stacking", "_hydrogen_bonding", "_cross_stacking", "_coaxial_stacking"]:
        signature = f"number DNAInteraction::{term}(BaseParticle *p, BaseParticle *q, bool compute_r, bool update_forces) {{"
        edit(cpp, signature, signature + "\n    if(_peg_pair(p, q)) return 0.;\n")
    signature = "number DNAInteraction::_nonbonded_excluded_volume(BaseParticle *p, BaseParticle *q, bool compute_r, bool update_forces) {"
    edit(cpp, signature, signature + r'''
    if(_peg_pair(p, q)) {
        if(p->is_bonded(q)) return 0.;
        if(compute_r) _computed_r = _box->min_image(p->pos, q->pos);
        return _peg_repulsion(p, q, update_forces);
    }
''')
    edit(cpp, "\t\tif(_use_mbf) {\n\t\t\tcontinue;", r'''
        if(_peg_model && _peg_particle(p)) {
            for(BaseParticle *q : {p->n3, p->n5}) if(q != P_VIRTUAL) {
                if(!_peg_particle(q)) throw oxDNAException("DNA2PEG does not support covalent PEG-DNA bonds");
                number length = (q->pos - p->pos).module();
                if(!std::isfinite(length) || length < 0.1 * _peg_bond_length || length > 3. * _peg_bond_length)
                    throw oxDNAException("Invalid PEG spring length for particle %d", p->index);
            }
            continue;
        }
        if(_use_mbf) {
            continue;''')
    edit(cpp, "\t*N_strands = parser.N_strands();", r'''
    if(_peg_model) {
        for(BaseParticle *p : particles) {
            for(BaseParticle *q : {p->n3, p->n5}) if(q != P_VIRTUAL && _peg_particle(p) != _peg_particle(q))
                throw oxDNAException("DNA2PEG does not support covalent PEG-DNA bonds");
        }
    }
    *N_strands = parser.N_strands();''')
    changes[cpp] += r'''

number DNAInteraction::_peg_spring(BaseParticle *p, BaseParticle *q, bool update_forces) {
    number r = _computed_r.module();
    number dr = r - _peg_bond_length;
    if(r < 1.e-12) throw oxDNAException("Coincident PEG bonded beads");
    if(update_forces) {
        LR_vector force = _computed_r * (_peg_bond_k * dr / r);
        p->force += force;
        q->force -= force;
    }
    return 0.5 * _peg_bond_k * dr * dr;
}

number DNAInteraction::_peg_repulsion(BaseParticle *p, BaseParticle *q, bool update_forces) {
    number sigma = (_peg_particle(p) && _peg_particle(q)) ? _peg_sigma : _peg_dna_sigma;
    number r2 = _computed_r.norm();
    if(_peg_epsilon == 0. || r2 >= std::pow(2., 1./3.) * sigma * sigma) return 0.;
    if(r2 < 1.e-12) throw oxDNAException("Coincident PEG steric sites");
    number s2 = sigma * sigma / r2;
    number s6 = s2 * s2 * s2;
    if(update_forces) {
        LR_vector force = _computed_r * (24. * _peg_epsilon * (s6 - 2. * s6 * s6) / r2);
        p->force += force;
        q->force -= force;
    }
    return 4. * _peg_epsilon * (s6 * s6 - s6) + _peg_epsilon;
}
'''
    for term in ["_coaxial_stacking", "_debye_huckel"]:
        name = "src/Interactions/DNA2Interaction.cpp"
        signature = f"number DNA2Interaction::{term}(BaseParticle *p, BaseParticle *q, bool compute_r, bool update_forces) {{"
        edit(name, signature, signature + "\n    if(_peg_pair(p, q)) return 0.;\n")
    edit("src/Interactions/InteractionFactory.cpp", 'else if(inter_type.compare("DNA2") == 0)', 'else if(inter_type.compare("DNA2") == 0 || inter_type.compare("DNA2PEG") == 0)')
    edit("src/CUDA/Interactions/CUDAInteractionFactory.cu", '!inter_type.compare("DNA2"))', '!inter_type.compare("DNA2") || !inter_type.compare("DNA2PEG"))')
    cuda = "src/CUDA/Interactions/CUDADNAInteraction.cu"
    edit(cuda, 'if(inter_type.compare("DNA2") == 0)', 'if(inter_type.compare("DNA2") == 0 || inter_type.compare("DNA2PEG") == 0)')
    edit(cuda, "void CUDADNAInteraction::cuda_init(int N) {", "void CUDADNAInteraction::cuda_init(int N) {" + r'''
    int peg_enabled = _peg_model ? 1 : 0;
    CUDA_SAFE_CALL(cudaMemcpyToSymbol(MD_peg_enabled, &peg_enabled, sizeof(int)));
    float peg_values[5] = {float(_peg_bond_length), float(_peg_bond_k), float(_peg_sigma), float(_peg_dna_sigma), float(_peg_epsilon)};
    CUDA_SAFE_CALL(cudaMemcpyToSymbol(MD_peg_values, peg_values, 5 * sizeof(float)));
''')
    kernel = "src/CUDA/Interactions/CUDA_DNA.cuh"
    edit(kernel, "template<bool qIsN3>\n__device__ void _bonded_part", r'''
__constant__ int MD_peg_enabled;
__constant__ float MD_peg_values[5]; // b, k, PEG sigma, mixed sigma, epsilon

template<bool qIsN3>
__device__ void _bonded_part''')
    edit(kernel, "\tint n3type = get_particle_type(n3pos);", r'''
    if(MD_peg_enabled && get_particle_btype(n3pos) == 500 && get_particle_btype(n5pos) == 500) {
        c_number length = _module(r);
        c_number delta = length - MD_peg_values[0];
        c_number4 f = r * (MD_peg_values[1] * delta / fmaxf(length, 1.e-12f));
        f.w = 0.5f * MD_peg_values[1] * delta * delta;
        if(qIsN3) F += f;
        else { F.x -= f.x; F.y -= f.y; F.z -= f.z; F.w += f.w; }
        return;
    }
    int n3type = get_particle_type(n3pos);''')
    edit(kernel, "\tint int_type = pbtype + qbtype;", r'''
    if(MD_peg_enabled && (pbtype == 500 || qbtype == 500)) {
        c_number sigma = (pbtype == 500 && qbtype == 500) ? MD_peg_values[2] : MD_peg_values[3];
        c_number r2 = CUDA_DOT(r, r);
        if(MD_peg_values[4] > 0.f && r2 < 1.2599210499f * sigma * sigma) {
            r2 = fmaxf(r2, 1.e-12f);
            c_number s2 = sigma * sigma / r2;
            c_number s6 = s2 * s2 * s2;
            c_number4 f = r * (24.f * MD_peg_values[4] * (s6 - 2.f * s6 * s6) / r2);
            f.w = 4.f * MD_peg_values[4] * (s6 * s6 - s6) + MD_peg_values[4];
            F += f;
        }
        return;
    }
    int int_type = pbtype + qbtype;''')
    # All replacements validated before writing; a mismatch leaves the source clean.
    for name, text in changes.items():
        (source / name).write_text(text)


if __name__ == "__main__":
    patch(Path(sys.argv[1]))
