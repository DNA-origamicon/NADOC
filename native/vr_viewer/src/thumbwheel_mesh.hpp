#pragma once
#include "interaction.hpp"
#include <glm/gtc/constants.hpp>

namespace nadoc_vr {
// A physical cylinder with trapezoidal raised ribs, cut at the panel surface.
// exposure is the visible fraction of the circumference (0.5 = half a wheel).
struct ThumbwheelShape {
    float radius=.06F, width=.08F, exposure=.35F, ridgeHeight=.0025F;
    int ridges=32;
    float centerDepth() const {return -radius*std::cos(glm::pi<float>()*exposure);}
    float halfOpening() const {return radius*std::sin(glm::pi<float>()*exposure);}
};
inline float thumbwheelRangeRadius(int maximum) {
    // Compress orders of magnitude; a thousand values must not mean a 100x panel.
    return .045F+.0375F*std::clamp(std::log10(float(std::max(10,maximum)))-1.F,0.F,2.F);
}
inline ThumbwheelShape thumbwheelPreset(int maximum,float exposure=.35F) {
    return {thumbwheelRangeRadius(maximum),.09F,exposure,.0025F,32};
}
inline std::optional<glm::vec3> thumbwheelHit(const ThumbwheelShape& s,glm::vec3 center,
        const MenuPlacement& placement,const HandPose& hand) {
    if(!hand.valid)return std::nullopt;
    const float cutoff=center.z;center.z+=s.centerDepth();
    const auto origin=placement.localPoint(hand.position);
    const auto direction=glm::normalize(placement.localPoint(hand.position+hand.orientation*glm::vec3(0,0,-1))-origin);
    const auto o=origin-center;const float r=s.radius+s.ridgeHeight;
    const float a=direction.y*direction.y+direction.z*direction.z;
    const float b=2*(o.y*direction.y+o.z*direction.z),cc=o.y*o.y+o.z*o.z-r*r;
    float nearest=1e9F;std::optional<glm::vec3> hit;
    auto candidate=[&](float t) {
        auto p=origin+direction*t;
        if(t>0 && t<nearest && p.z>=cutoff && std::abs(p.x-center.x)<=s.width*.5F+.002F) {nearest=t;hit=p;}
    };
    if(a>1e-8F && b*b-4*a*cc>=0) {
        const float root=std::sqrt(b*b-4*a*cc);
        candidate((-b-root)/(2*a));candidate((-b+root)/(2*a));
    }
    if(std::abs(direction.x)>1e-8F)for(float side:{-1.F,1.F}) {
        const float t=(center.x+side*s.width*.5F-origin.x)/direction.x;
        const auto p=origin+direction*t-center;
        if(p.y*p.y+p.z*p.z<=r*r)candidate(t);
    }
    return hit;
}
template<class Triangle> void thumbwheelMesh(const ThumbwheelShape& shape,float phase,
        glm::vec3 center,Triangle triangle) {
    const float cutoff=center.z;
    center.z+=shape.centerDepth();
    // Clip *geometry*, including raised ribs and end caps. A translucent menu
    // cannot accidentally reveal the hidden back of the cylinder.
    auto clipped=[&](glm::vec3 a,glm::vec3 b,glm::vec3 c) {
        const auto cross=glm::cross(c-a,b-a);
        if(glm::length(cross)<1e-10F)return;
        const auto normal=glm::normalize(cross);
        std::vector<glm::vec3> polygon;
        const std::array<glm::vec3,3> input{a,b,c};
        auto previous=input.back();
        for(auto current:input) {
            if((current.z>=cutoff)!=(previous.z>=cutoff))
                polygon.push_back(glm::mix(previous,current,(cutoff-previous.z)/(current.z-previous.z)));
            if(current.z>=cutoff)polygon.push_back(current);
            previous=current;
        }
        for(size_t i=1;i+1<polygon.size();++i)triangle(polygon[0],polygon[i],polygon[i+1],normal);
    };
    const int segments=shape.ridges*4;
    auto point=[&](int i,float x) {
        const float angle=glm::two_pi<float>()*(float(i)/4.F-phase)/shape.ridges;
        const float r=shape.radius+((i%4==1||i%4==2)?shape.ridgeHeight:0.F);
        return center+glm::vec3(x,std::cos(angle)*r,std::sin(angle)*r);
    };
    for(int i=0;i<segments;++i) {
        auto a=point(i,-shape.width*.5F),b=point(i,shape.width*.5F);
        auto c=point(i+1,shape.width*.5F),d=point(i+1,-shape.width*.5F);
        clipped(a,b,c);clipped(a,c,d);
        clipped(center+glm::vec3(-shape.width*.5F,0,0),a,d);
        clipped(center+glm::vec3(shape.width*.5F,0,0),c,b);
    }
}
}
