#pragma once
#include <string>
#include <vector>
#include <algorithm>
#include <cmath>
#include "ui_style.hpp"

namespace nadoc_vr {
// Input arbitration independent of rendering, frame rate and OpenXR transport.
class MenuFocus {
 public:
    static constexpr double kPointerDwellSeconds = .45;
    bool active = false;
    std::string id;
    void reset() { active=false; id.clear(); candidate_.clear(); blockedRay_.clear(); armed_=false; }
    void begin(const std::string& first, const std::string& ray) {
        active=true; id=first; blockedRay_=ray; armed_=ray.empty(); candidate_.clear();
    }
    void step(const std::vector<std::string>& ids, int direction) {
        if(ids.empty()) {reset();return;}
        auto it=std::find(ids.begin(),ids.end(),id);
        int index=it==ids.end()?0:static_cast<int>(it-ids.begin());
        index=std::clamp(index+direction,0,static_cast<int>(ids.size())-1);
        id=ids[static_cast<size_t>(index)];candidate_.clear();
    }
    // A ray already resting on a button when navigation starts cannot steal focus.
    // Leave that button, then dwell continuously on one target to resume pointing.
    bool pointer(const std::string& ray, double now, bool triggerHeld) {
        if(!active) return false;
        if(!armed_) {
            if(ray!=blockedRay_) armed_=true;
            else return false;
        }
        if(ray.empty() || triggerHeld) {candidate_.clear();return false;}
        if(ray!=candidate_) {candidate_=ray;since_=now;return false;}
        if(now-since_ < kPointerDwellSeconds) return false;
        reset(); return true;
    }
 private:
    std::string blockedRay_,candidate_;
    bool armed_=false;
    double since_=0;
};
}
