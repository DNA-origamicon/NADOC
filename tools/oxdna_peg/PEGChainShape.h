// Linear-chain shape diagnostics without writing full configurations.
#ifndef NADOC_PEG_CHAIN_SHAPE_H
#define NADOC_PEG_CHAIN_SHAPE_H
#include "BaseObservable.h"
#include "../Particles/Molecule.h"
#include "../Utilities/Utils.h"

class PEGChainShape: public BaseObservable {
public:
    std::string get_output_string(llint) override {
        number mean_rg=0, mean_rg2=0;
        const auto &molecules=_config_info->molecules();
        if(molecules.empty()) throw oxDNAException("peg_chain_shape requires molecules");
        for(const auto &molecule:molecules) {
            const auto &p=molecule->particles;
            if(p.empty()) throw oxDNAException("peg_chain_shape encountered empty molecule");
            std::vector<LR_vector> positions(p.size());
            positions[0]=LR_vector(0,0,0);
            LR_vector center(0,0,0);
            for(size_t i=1;i<p.size();i++) {
                if(p[i-1]->n3!=p[i] && p[i-1]->n5!=p[i])
                    throw oxDNAException("peg_chain_shape requires ordered linear molecules");
                positions[i]=positions[i-1]+_config_info->box->min_image(p[i-1]->pos,p[i]->pos);
                center+=positions[i];
            }
            center/=number(p.size());
            number rg2=0;
            for(const auto &position:positions) rg2+=(position-center).norm();
            rg2*=number(0.8518*0.8518)/p.size();
            mean_rg+=sqrt(rg2);mean_rg2+=rg2;
        }
        // Arithmetic mean Rg [nm], arithmetic mean Rg^2 [nm^2] over molecules.
        return Utils::sformat("%.12g %.12g",mean_rg/molecules.size(),mean_rg2/molecules.size());
    }
};
#endif
