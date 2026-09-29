#pragma once
#include "menu_layout.hpp"
#include <chrono>
#include <optional>

namespace nadoc_vr {
// Row-space animation keeps drawing and pointer hit rectangles in agreement.
struct SidebarScroll {
    float from=0, target=0;
    double started=0;
    static double now() {
        return std::chrono::duration<double>(std::chrono::steady_clock::now().time_since_epoch()).count();
    }
    float value(float expected,double time) const {
        if(expected!=target) return expected; // page/tab/collapse changes are immediate
        const float t=std::clamp(float((time-started)/.20),0.F,1.F);
        return from+(target-from)*t*t*(3.F-2.F*t);
    }
    void move(float old,float next,double time) {
        from=value(old,time);target=next;started=time;
    }
};
inline MenuPanelBounds clipSidebarBounds(MenuPanelBounds b,const MenuPanelBounds& clip) {
    b.minimum=glm::max(b.minimum,clip.minimum);
    b.maximum=glm::min(b.maximum,clip.maximum);
    return b;
}
inline bool clipSidebarLine(glm::vec3& a,glm::vec3& b,const MenuPanelBounds& clip) {
    const auto delta=b-a;
    float lo=0,hi=1;
    for(int axis=0;axis<2;++axis) {
        if(std::abs(delta[axis])<1e-8F) {
            if(a[axis]<clip.minimum[axis] || a[axis]>clip.maximum[axis])return false;
        } else {
            float x=(clip.minimum[axis]-a[axis])/delta[axis],y=(clip.maximum[axis]-a[axis])/delta[axis];
            if(x>y)std::swap(x,y);
            lo=std::max(lo,x);hi=std::min(hi,y);
            if(lo>hi)return false;
        }
    }
    b=a+delta*hi;a+=delta*lo;return true;
}
}
