// NADOC's provisional isomer-specific rigid-body weld, in oxDNA reduced units.
// The additional affected pair is permanent and independent of neighbour lists.
#include "Interactions/DNA2Interaction.h"
#include "Particles/DNANucleotide.h"
#include <fstream>
#include <map>
#include <set>
#include <cmath>
#include <algorithm>

class CpdNucleotide : public DNANucleotide {
public:
    BaseParticle *weld = nullptr;
    explicit CpdNucleotide(int groove) : DNANucleotide(groove) {}
    bool is_bonded(BaseParticle *q) override {
        return q == weld || DNANucleotide::is_bonded(q);
    }
};

class CpdDNA2 : public DNA2Interaction {
    struct Spring { LR_vector a, b; number length, stiffness; };
    struct Weld { int first, second; std::vector<Spring> springs; };
    std::map<std::pair<int,int>, Weld> welds;
    std::string filename;
    Weld *find(BaseParticle *p, BaseParticle *q) {
        if(p == P_VIRTUAL || q == P_VIRTUAL) return nullptr;
        auto it = welds.find(std::minmax(p->index, q->index));
        return it == welds.end() ? nullptr : &it->second;
    }
public:
    void get_settings(input_file &inp) override {
        DNA2Interaction::get_settings(inp);
        getInputString(&inp, "cpd_file", filename, 1);
    }
    void allocate_particles(std::vector<BaseParticle *> &particles) override {
        for(auto &p : particles) p = new CpdNucleotide(_grooving);
    }
    void read_topology(int *count, std::vector<BaseParticle *> &particles) override {
        DNA2Interaction::read_topology(count, particles);
        std::ifstream input(filename);
        int n, version;
        std::string magic;
        if(!(input >> magic >> version >> n) || magic != "NADOC_CPD" || version != 1 || n < 1)
            throw oxDNAException("Invalid CPD interaction file");
        std::set<int> used;
        for(int w=0; w<n; ++w) {
            Weld weld;
            int ns;
            if(!(input >> weld.first >> weld.second >> ns) || ns != 16 ||
               weld.first < 0 || weld.second < 0 || weld.first >= int(particles.size()) ||
               weld.second >= int(particles.size()) || !used.insert(weld.first).second ||
               !used.insert(weld.second).second)
                throw oxDNAException("Invalid or overlapping CPD endpoints");
            auto p = particles[weld.first], q = particles[weld.second];
            if(p->type != 3 || q->type != 3) throw oxDNAException("CPD endpoints must be thymine");
            for(int s=0;s<ns;++s) {
                Spring spring;
                if(!(input >> spring.a.x >> spring.a.y >> spring.a.z >>
                     spring.b.x >> spring.b.y >> spring.b.z >> spring.length >> spring.stiffness) ||
                   !std::isfinite(spring.a.x) || !std::isfinite(spring.a.y) || !std::isfinite(spring.a.z) ||
                   !std::isfinite(spring.b.x) || !std::isfinite(spring.b.y) || !std::isfinite(spring.b.z) ||
                   !std::isfinite(spring.length) || !std::isfinite(spring.stiffness) ||
                   spring.length <= 0 || spring.stiffness < 0)
                    throw oxDNAException("Invalid CPD spring");
                weld.springs.push_back(spring);
            }
            bool adjacent = p->n3 == q || p->n5 == q;
            static_cast<CpdNucleotide *>(p)->weld = q;
            static_cast<CpdNucleotide *>(q)->weld = p;
            if(!adjacent) {
                p->affected.push_back(ParticlePair(p,q));
                q->affected.push_back(ParticlePair(p,q));
            }
            welds.emplace(std::minmax(weld.first,weld.second), weld);
        }
        std::string extra;
        if(input >> extra) throw oxDNAException("Trailing CPD interaction records");
        OX_LOG(Logger::LOG_INFO, "NADOC_CPD_V1: %d permanent CPD welds", n);
    }
    number pair_interaction(BaseParticle *p, BaseParticle *q, bool compute_r=true, bool forces=false) override {
        if(find(p,q)) return pair_interaction_bonded(p,q,true,forces);
        return DNA2Interaction::pair_interaction(p,q,compute_r,forces);
    }
    number pair_interaction_nonbonded(BaseParticle *p, BaseParticle *q, bool compute_r=true, bool forces=false) override {
        if(find(p,q)) return 0.;
        return DNA2Interaction::pair_interaction_nonbonded(p,q,compute_r,forces);
    }
    number pair_interaction_bonded(BaseParticle *p, BaseParticle *q, bool compute_r=true, bool forces=false) override {
        auto weld = find(p,q);
        if(!weld) return DNA2Interaction::pair_interaction_bonded(p,q,compute_r,forces);
        if(p->index != weld->first) std::swap(p,q);
        p->set_positions(); q->set_positions();
        // Existing backbone connectivity survives. Ordinary base-base terms of
        // the reacted pair are replaced by the fitted product interaction.
        number energy = 0.;
        if(p->n3 == q || p->n5 == q) energy += _backbone(p,q,true,forces);
        auto centre = _box->min_image(p->pos, q->pos);
        for(auto &s : weld->springs) {
            auto a = p->orientation*s.a, b = q->orientation*s.b;
            auto r = centre+b-a;
            number distance = r.module();
            if(distance < 1.e-12) throw oxDNAException("Collapsed CPD virtual-site distance");
            number delta = distance-s.length;
            energy += .5*s.stiffness*delta*delta;
            if(forces) {
                auto f = r*(s.stiffness*delta/distance);
                p->force += f; q->force -= f;
                _update_stress_tensor(p, q, centre, -f);
                p->torque += p->orientationT*(a.cross(f));
                q->torque -= q->orientationT*(b.cross(f));
            }
        }
        return energy;
    }
};
extern "C" BaseInteraction *make_CpdDNA2() { return new CpdDNA2(); }
extern "C" BaseInteraction *make_interaction() { return new CpdDNA2(); }
