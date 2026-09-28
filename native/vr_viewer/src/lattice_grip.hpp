#pragma once
#include "interaction.hpp"
namespace nadoc_vr {
// Interior grips latch independently, so the first hand never moves the scene
// while waiting for the second. Separation is projected onto the panel plane:
// reaching through the panel does not accidentally zoom its contents.
class LatticeGrip {
 public:
    static constexpr float kDepthMeters=.09F;
    float zoom=1.F;
    std::array<bool,2> held{},nearby{};
    bool scaling=false;
    void cancel() { held.fill(false);nearby.fill(false);scaling=false; }
    std::array<bool,2> update(const MenuPlacement& panel,
        const std::array<HandPose,2>& hands,const std::array<bool,2>& clicked,
        glm::vec2 minimum,glm::vec2 maximum,glm::vec2 frameMin,glm::vec2 frameMax,
        bool available) {
        if(!available) {cancel();return held;}
        for(size_t h=0;h<2;++h) {
            nearby[h]=panel.nearPanel(hands[h],minimum,maximum,kDepthMeters) &&
                !panel.nearBorder(hands[h],frameMin,frameMax);
            if(!hands[h].valid || !hands[h].pressed)held[h]=false;
            else if(clicked[h] && nearby[h])held[h]=true;
        }
        const auto delta=panel.localPoint(hands[1].position)-panel.localPoint(hands[0].position);
        const float distance=glm::length(glm::vec2(delta))*panel.scale();
        if(held[0] && held[1]) {
            if(!scaling && distance>=.04F) {scaling=true;initialDistance=distance;initialZoom=zoom;}
            if(scaling)zoom=glm::clamp(initialZoom*distance/initialDistance,.1F,10.F);
        } else scaling=false;
        return held;
    }
 private:
    float initialDistance=1,initialZoom=1;
};
}
