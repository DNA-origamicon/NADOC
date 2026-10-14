#pragma once
#include "menu_layout.hpp"

namespace nadoc_vr {
// Compact tab animation shared by drawing, ray targets and exported geometry.
// No invisible hit padding or dwell enlargement: profile tests see the real surface.
struct CompactTabs {
    static constexpr float idleLength=.105F, gap=.012F;
    static constexpr float idleFont=.0033F, expandedFont=.0045F;
    std::vector<float> growth;
    void step(size_t count,size_t selected,int hover,float dt) {
        growth.resize(count,0);
        for(size_t i=0;i<count;++i){const float target=i==selected || int(i)==hover?1.F:0.F;
            growth[i]+=std::clamp(target-growth[i],-dt*5.F,dt*5.F);
        }
    }
    float amount(size_t i) const {return i<growth.size()?growth[i]:0;}
    float font(size_t i) const {return idleFont+amount(i)*(expandedFont-idleFont);}
    float length(size_t i,size_t letters) const {
        return idleLength+amount(i)*(std::max(idleLength,strokeTextWidth(letters,expandedFont)+.020F)-idleLength);
    }
};
}
