// DNA2 conditional dynamics: fixed-fixed backbone energy is a constant offset.
// Keep topology, terminal charges, stacking and every mobile-involving force.
#include "Interactions/DNA2Interaction.h"
#include "Particles/DNANucleotide.h"
#include <fstream>
#include <set>

class SubmodelDNA2 : public DNA2Interaction {
    std::set<int> mobile;
    bool fixed_pair(BaseParticle *p, BaseParticle *q) const {
        if (p == P_VIRTUAL) return false;
        if (q == P_VIRTUAL) q = p->n3;
        return q != P_VIRTUAL && !mobile.count(p->index) && !mobile.count(q->index);
    }
protected:
    number _backbone(BaseParticle *p, BaseParticle *q, bool compute_r, bool update_forces) override {
        if (fixed_pair(p, q)) return 0.;
        return DNA2Interaction::_backbone(p, q, compute_r, update_forces);
    }
public:
    void get_settings(input_file &inp) override {
        DNA2Interaction::get_settings(inp);
        std::string path;
        getInputString(&inp, "submodel_mobile_file", path, 1);
        std::ifstream stream(path);
        int id;
        while (stream >> id) {
            if (id < 0 || !mobile.insert(id).second)
                throw oxDNAException("Invalid or duplicate submodel mobile index");
        }
        if (!stream.eof() || mobile.empty()) throw oxDNAException("Invalid submodel mobile file");
    }
    void check_input_sanity(std::vector<BaseParticle *> &particles) override {
        if (*mobile.rbegin() >= static_cast<int>(particles.size()))
            throw oxDNAException("Submodel mobile index exceeds particle count");
        // Retain upstream topology validation. Then check precisely the FENE
        // terms that remain in this conditional Hamiltonian, with native bounds.
        const bool capped = _use_mbf;
        _use_mbf = true;
        try { DNA2Interaction::check_input_sanity(particles); }
        catch (...) { _use_mbf = capped; throw; }
        _use_mbf = capped;
        if (!capped) {
            for (auto p : particles) {
                p->set_positions();
                for (auto q : {p->n3, p->n5}) {
                    if (q == P_VIRTUAL || fixed_pair(p, q)) continue;
                    q->set_positions();
                    auto r = p->pos + p->int_centers[DNANucleotide::BACK]
                           - q->pos - q->int_centers[DNANucleotide::BACK];
                    number d = r.module();
                    if (d > _fene_r0 + FENE_DELTA || d < _fene_r0 - FENE_DELTA)
                        throw oxDNAException("Mobile-region bond %d--%d exceeds FENE bounds (d = %lf); relax this region or enlarge the mobile box", p->index, q->index, d);
                }
            }
        }
        OX_LOG(Logger::LOG_INFO, "SUBMODEL_DNA2_V2: fixed-fixed backbone energy omitted; topology and all mobile-involving interactions unchanged");
    }
};
extern "C" BaseInteraction *make_interaction() { return new SubmodelDNA2(); }
