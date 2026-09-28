#pragma once
#include "interaction.hpp"

namespace nadoc_vr {
// A head-relative, yaw-only quiver. A hand must first dwell in front, then
// dwell behind the shoulder; remaining behind cannot repeatedly toggle tools.
class QuiverGesture {
 public:
    std::array<bool,2> armed{},inside{};
    std::array<double,2> frontSince{-1,-1},behindSince{-1,-1};
    std::array<glm::vec3,2> frontPosition{};
    uint64_t sequence=0;
    void reset() {armed={};inside={};frontSince={-1,-1};behindSince={-1,-1};}
    static glm::vec3 local(glm::vec3 hand,glm::vec3 head,glm::quat orientation) {
        auto forward=orientation*glm::vec3(0,0,-1);forward.y=0;
        if(glm::length(forward)<.1F)return {0,-10,0};
        forward=glm::normalize(forward);
        const auto delta=hand-head;
        return {glm::dot(delta,glm::cross(forward,glm::vec3(0,1,0))),delta.y,-glm::dot(delta,forward)};
    }
    std::optional<size_t> update(const std::array<HandPose,2>& hands,glm::vec3 head,
        glm::quat orientation,double now,bool enabled) {
        if(!enabled){reset();return std::nullopt;}
        for(size_t h=0;h<2;++h) {
            if(!hands[h].valid){armed[h]=inside[h]=false;frontSince[h]=behindSince[h]=-1;continue;}
            const auto p=local(hands[h].position,head,orientation);
            const bool front=p.z<-.12F && glm::length(p)<1.2F;
            if(!armed[h]) {
                if(!front)frontSince[h]=-1;
                else if(frontSince[h]<0)frontSince[h]=now;
                else if(now-frontSince[h]>=.15)armed[h]=true;
            }
            if(front)frontPosition[h]=hands[h].position;
            const bool travelled=glm::distance(frontPosition[h],hands[h].position)>.18F;
            const bool inner=std::abs(p.x)<.55F && p.y>-.25F && p.y<.35F && p.z>.12F && p.z<.55F;
            const bool outer=std::abs(p.x)<.65F && p.y>-.35F && p.y<.45F && p.z>.06F && p.z<.65F;
            inside[h]=inner || (inside[h]&&outer);
            if(!armed[h] || !inside[h] || !travelled)behindSince[h]=-1;
            else if(behindSince[h]<0)behindSince[h]=now;
            else if(now-behindSince[h]>=.35) {
                reset();++sequence;return h;
            }
        }
        return std::nullopt;
    }
};
}
