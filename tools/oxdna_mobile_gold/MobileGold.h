#pragma once
// NADOC_MOBILE_GOLD_V1. File units: oxDNA length, energy and nucleotide mass.
#include <fstream>
#include <vector>
#include <cmath>
#include "../Utilities/oxDNAException.h"
struct GoldCore { int index; float radius, mass, inertia, diffusion, rotation_diffusion; };
struct GoldCoating { int core; float x,y,z,radius; };
struct GoldGraft { int dna, core; float x,y,z,length,k; };
struct GoldModel {
    std::vector<GoldCore> cores;
    std::vector<GoldCoating> coating;
    std::vector<GoldGraft> grafts;
    int dna_count=0;
    float clearance=0.4f, exclusion_k=100.f;
    void load(const std::string &path) {
        std::ifstream in(path); int nc=0, ng=0;
        if(!(in >> dna_count >> nc >> ng >> clearance >> exclusion_k) || dna_count<1 || nc<1 || nc>64 || ng<0 || ng>dna_count || !(clearance>=0) || !(exclusion_k>0))
            throw oxDNAException("Invalid mobile gold header");
        cores.resize(nc); grafts.resize(ng);
        for(int j=0;j<nc;j++) {
            auto &c=cores[j];
            if(!(in>>c.index>>c.radius>>c.mass>>c.inertia>>c.diffusion>>c.rotation_diffusion) || c.index!=dna_count+j || !(c.radius>0) || !(c.mass>0) || !(c.inertia>0) || !(c.diffusion>0) || !(c.rotation_diffusion>0))
                throw oxDNAException("Invalid mobile gold core");
            for(float v: {c.radius,c.mass,c.inertia,c.diffusion,c.rotation_diffusion}) if(!std::isfinite(v)) throw oxDNAException("Nonfinite gold core");
        }
        std::vector<bool> seen(dna_count,false);
        for(auto &g:grafts) {
            if(!(in>>g.dna>>g.core>>g.x>>g.y>>g.z>>g.length>>g.k) || g.dna<0 || g.dna>=dna_count || g.core<0 || g.core>=nc || seen[g.dna] || !(g.length>0) || !(g.k>0))
                throw oxDNAException("Invalid mobile gold graft");
            for(float v: {g.x,g.y,g.z,g.length,g.k}) if(!std::isfinite(v)) throw oxDNAException("Nonfinite gold graft");
            seen[g.dna]=true;

        }
        if(!std::isfinite(clearance)||!std::isfinite(exclusion_k)) throw oxDNAException("Nonfinite gold exclusion");
        std::string extra;
        if(in>>extra) {
            int count=0;
            if(extra!="COATING_V1" || !(in>>count) || count<1 || count>256) throw oxDNAException("Invalid gold coating header");
            coating.resize(count);
            for(auto &s:coating) {
                if(!(in>>s.core>>s.x>>s.y>>s.z>>s.radius) || s.core<0 || s.core>=nc || !(s.radius>0)) throw oxDNAException("Invalid gold coating sphere");
                for(float v:{s.x,s.y,s.z,s.radius}) if(!std::isfinite(v)) throw oxDNAException("Nonfinite coating sphere");
            }
            if(in>>extra) throw oxDNAException("Unexpected mobile gold data");
        }
        for(auto &g:grafts) {
            bool coated=false; for(auto &s:coating) if(s.core==g.core) coated=true;
            if(!coated && std::abs(std::sqrt(g.x*g.x+g.y*g.y+g.z*g.z)-cores[g.core].radius)>1.e-4f)
                throw oxDNAException("Gold graft must lie on core surface");
        }
    }
};
