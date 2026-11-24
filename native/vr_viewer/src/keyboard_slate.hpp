#pragma once
#include <algorithm>
#include <cmath>
#include <string>
#include <glm/glm.hpp>

// Shared by the approved desktop study and production VR keyboard.
namespace keyboard_slate {
inline constexpr float restDepth=.026F,travel=.006F;
inline float amount(float pressure){return std::isfinite(pressure)?std::clamp(pressure,0.F,1.F):0.F;}
inline float depth(float pressure){return restDepth-travel*amount(pressure);}
template<class Ui> void key(Ui& ui,float x,float y,float w,float h,const std::string& label,
        bool enabled,bool hover,bool selected,float pressure,bool backspace=false){
    const auto face=!enabled?glm::vec3(.16F,.19F,.23F):selected?glm::vec3(.13F,.36F,.44F):glm::vec3(.16F,.24F,.33F);
    const auto edge=hover?glm::vec3(.95F,.70F,.30F):selected?glm::vec3(.35F,.76F,1):glm::vec3(.35F,.46F,.58F);
    const float z=depth(enabled?pressure:0.F),font=backspace?.0028F:.0045F;
    ui.raisedSlate(x,y,w,h,z,face,edge);
    ui.text(label,x+(w-float(label.size()*6-1)*font)*.5F,y+h*.56F,font,
        enabled?glm::vec3(.9F,.94F,1):glm::vec3(.55F,.66F,.77F),z+.004F);
}
}
