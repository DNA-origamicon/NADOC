#pragma once
#include "interaction.hpp"

namespace nadoc_vr {
// Mirrored shoulder holsters in the horizontal head frame. Enter with the
// controller pointing upward/backward; return in front to rearm, without timers.
class QuiverGesture {
 public:
    std::array<bool,2> armed{},inside{};
    std::array<glm::vec3,2> frontPosition{};
    uint64_t sequence=0;
    void reset() {armed={};inside={};}
    static glm::vec3 local(glm::vec3 hand,glm::vec3 head,glm::quat orientation) {
        auto forward=orientation*glm::vec3(0,0,-1);forward.y=0;
        if(glm::length(forward)<.1F)return {0,-10,0};
        forward=glm::normalize(forward);
        const auto delta=hand-head;
        return {glm::dot(delta,glm::cross(forward,glm::vec3(0,1,0))),delta.y,-glm::dot(delta,forward)};
    }
    std::optional<size_t> update(const std::array<HandPose,2>& hands,glm::vec3 head,
        glm::quat orientation,double /*now*/,const std::array<bool,2>& enabled) {
        for(size_t h=0;h<2;++h) {
            if(!enabled[h] || !hands[h].valid){armed[h]=inside[h]=false;continue;}
            const auto p=local(hands[h].position,head,orientation);
            const bool front=p.z<-.12F && glm::length(p)<1.2F;
            if(front) {armed[h]=true;frontPosition[h]=hands[h].position;}
            const bool travelled=glm::distance(frontPosition[h],hands[h].position)>.18F;
            const float side=p.x*(h==0?-1.F:1.F);
            // 12–45 cm to the matching side, 10 cm below to 30 cm above
            // eye height, from the ear plane to 35 cm behind it.
            const auto aim=local(head+hands[h].orientation*glm::vec3(0,0,-1),head,orientation);
            const bool oriented=glm::dot(aim,glm::normalize(glm::vec3(0,1,1)))>=.70710678F;
            inside[h]=side>=.12F && side<=.45F && p.y>=-.10F && p.y<=.30F && p.z>=0 && p.z<=.35F && oriented;
            if(armed[h] && inside[h] && travelled) {
                armed[h]=false;++sequence;return h;
            }
        }
        return std::nullopt;
    }
    std::optional<size_t> update(const std::array<HandPose,2>& hands,glm::vec3 head,
        glm::quat orientation,double now,bool enabled) {
        return update(hands,head,orientation,now,std::array<bool,2>{enabled,enabled});
    }
};
}
