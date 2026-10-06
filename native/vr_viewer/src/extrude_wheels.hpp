#pragma once
#include "thumbwheel_mesh.hpp"
#include "menu_layout.hpp"

namespace nadoc_vr {
inline constexpr std::array<const char*,2> kExtrudeWheelIds{
    "extrude:coarse-wheel", "extrude:fine-wheel"};
inline constexpr std::array<MenuPanelBounds,2> kExtrudeWheelBounds{{
    {{.015F,.261F},{.175F,.517F}},
    {{.215F,.261F},{.375F,.517F}},
}};
inline std::optional<size_t> extrudeWheelIndex(const std::string& id) {
    for(size_t i=0;i<kExtrudeWheelIds.size();++i)if(id==kExtrudeWheelIds[i])return i;
    return std::nullopt;
}
inline ThumbwheelShape extrudeWheelShape() { return thumbwheelPreset(1000); }
inline glm::vec3 extrudeWheelCenter(size_t index) {
    const auto& b=kExtrudeWheelBounds.at(index);
    return {(b.minimum.x+b.maximum.x)*.5F,.375F,.012F};
}
inline glm::vec3 extrudeWheelFront(size_t index) {
    const auto shape=extrudeWheelShape();
    return extrudeWheelCenter(index)+glm::vec3(0,0,shape.centerDepth()+shape.radius+shape.ridgeHeight);
}
inline int extrudeWheelStep(bool square,size_t index) {
    return index==0?latticeBasePairPeriod(square):1;
}
}
