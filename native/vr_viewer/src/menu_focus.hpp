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
        index=(index+direction+static_cast<int>(ids.size()))%static_cast<int>(ids.size());
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

namespace nadoc_vr {
// Adapter for the existing detailed native menus. Their stable hit IDs feed the
// same focus/dwell policy; activation still goes through production menu input.
class MenuFocusList {
 public:
    MenuFocus focus;
    template<class Entries> bool trackpad(const Entries& entries,const std::string& page,
            int ray,float x,float y) {
        const auto ids=targets(entries);
        if(ids.empty()) return false;
        if(!focus.active || page!=page_) {page_=page;focus.begin(ids.front(),key(ray));return true;}
        if(x*x+y*y<.45F*.45F) {focus.reset();return true;}
        focus.step(ids,std::abs(x)>std::abs(y)?(x>0?1:-1):(y>0?-1:1));
        focus.begin(focus.id,key(ray));
        return true;
    }
    template<class Entries> int resolve(const Entries& entries,const std::string& page,
            int ray,double now,bool held) {
        if(!focus.active) return ray;
        const auto ids=targets(entries);
        if(ids.empty()) {focus.reset();return ray;}
        if(page!=page_ || std::find(ids.begin(),ids.end(),focus.id)==ids.end()) {
            page_=page;focus.begin(ids.front(),key(ray));
        }
        focus.pointer(key(ray),now,held);
        return focus.active?std::stoi(focus.id):ray;
    }
    template<class Entries,class Line> void draw(const Entries& entries,Line line) const {
        if(!focus.active) return;
        for(const auto& e:entries) if(key(e.hit)==focus.id) {
            const auto r=e.hitHalfRight*.96F, u=e.hitHalfUp*.90F;
            const auto a=e.worldPosition-r-u, b=e.worldPosition+r-u;
            const auto c=e.worldPosition+r+u, d=e.worldPosition-r+u;
            line(a,b,ui_style::focus);line(b,c,ui_style::focus);
            line(c,d,ui_style::focus);line(d,a,ui_style::focus);
            return;
        }
    }
 private:
    std::string page_;
    static std::string key(int hit) {return hit<0?"":std::to_string(hit);}
    template<class Entries> static std::vector<std::string> targets(const Entries& entries) {
        std::vector<std::string> ids;
        for(const auto& e:entries) if(e.hit>=0 && e.hit<10000) ids.push_back(key(e.hit));
        return ids;
    }
};
}
