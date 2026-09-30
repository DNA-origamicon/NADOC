#pragma once
#include <glm/glm.hpp>
#include "menu_layout.hpp"
#include <cmath>
#include <string_view>
#include <array>
namespace nadoc_vr::ui_style {
// Native, unlit UI tokens. Scene lighting/shadows never change control contrast.
inline const glm::vec3 panel=glm::vec3(13,17,23)/255.F;
inline const glm::vec3 surface=glm::vec3(22,27,34)/255.F;
inline const glm::vec3 hover=glm::vec3(33,38,45)/255.F;
inline const glm::vec3 selected=glm::vec3(31,111,235)/255.F;
inline const glm::vec3 selectedBorder=glm::vec3(56,139,253)/255.F;
inline const glm::vec3 border=glm::vec3(72,79,88)/255.F;
inline const glm::vec3 disabledBorder=glm::vec3(63,70,79)/255.F;
inline const glm::vec3 text=glm::vec3(237,242,247)/255.F;
inline const glm::vec3 disabledText=glm::vec3(182,194,207)/255.F;
inline const glm::vec3 focus=glm::vec3(255,202,94)/255.F;
inline const glm::vec3 pressed=glm::vec3(45,85,115)/255.F;
inline const glm::vec3 accent=glm::vec3(88,166,255)/255.F;
inline const glm::vec3 danger=glm::vec3(248,81,73)/255.F;
// Desktop visualization hues (frontend/index.html .vt-btn/.sf-btn), plus
// shared success/danger tokens. Unmapped controls get a stable fallback hue.
inline glm::vec3 buttonAccent(std::string_view id) {
    constexpr auto desktop=std::to_array<std::pair<std::string_view,unsigned>>({
        {"lengthHeatmap",0xc084fc},{"sequences",0x4ade80},{"undefinedBases",0xfbbf24},
        {"loopSkips",0xff9944},{"grid",0x94a3b8},{"overhangNames",0xfb923c},
        {"clashes",0xff4d4d},{"deform",0xf97316},
        {"unfold",0x86efac},{"cadnano2d",0x818cf8},{"scaf",0x29b6f6},
        {"stap",0xef5350},{"xover",0x78d5f5},{"base",0xff7ad9}});
    auto rgb=[](unsigned c){return glm::vec3((c>>16)&255,(c>>8)&255,c&255)/255.F;};
    for(auto [key,value]:desktop)if(id.find(key)!=id.npos)return rgb(value);
    if(id.find("delete")!=id.npos||id.find("remove")!=id.npos||id=="close")return danger;
    if(id.find("save")!=id.npos||id.find("apply")!=id.npos||id.find("run")!=id.npos)return rgb(0x3fb950);
    if(id.starts_with("tab:")||id.starts_with("sim:engine")||id.find("repr")!=id.npos)return accent;
    constexpr std::array<unsigned,6> palette{0x58a6ff,0xa78bfa,0x2dd4bf,0xfbbf24,0xfb923c,0xf472b6};
    unsigned hash=2166136261u;for(unsigned char c:id)hash=(hash^c)*16777619u;
    return rgb(palette[hash%palette.size()]);
}
inline constexpr float cornerRadius=.012F;
// Rounded silhouettes using the same local geometry for fills and outlines.
template<class Line,class Fill> void rounded(MenuPanelBounds b,glm::vec3 bg,
        glm::vec3 edge,Line line,Fill fill,float radius=cornerRadius,float z=0) {
    const float r=std::min(radius,std::min(b.maximum.x-b.minimum.x,b.maximum.y-b.minimum.y)*.5F);
    fill({{b.minimum.x,b.minimum.y+r},{b.maximum.x,b.maximum.y-r}},bg);
    constexpr int slices=12;
    for(int i=0;i<slices;++i) {
        const float y0=r*i/slices,y1=r*(i+1)/slices;
        const float inset=r-std::sqrt(std::max(0.F,r*r-(r-(y0+y1)*.5F)*(r-(y0+y1)*.5F)));
        fill({{b.minimum.x+inset,b.minimum.y+y0},{b.maximum.x-inset,b.minimum.y+y1}},bg);
        fill({{b.minimum.x+inset,b.maximum.y-y1},{b.maximum.x-inset,b.maximum.y-y0}},bg);
    }
    glm::vec2 first{},previous{};
    for(int corner=0;corner<4;++corner) {
        const glm::vec2 center(corner==0||corner==3?b.maximum.x-r:b.minimum.x+r,
                               corner<2?b.maximum.y-r:b.minimum.y+r);
        for(int i=0;i<=8;++i) {
            const float angle=(corner+i/8.F)*1.570796327F;
            const glm::vec2 point=center+r*glm::vec2(std::cos(angle),std::sin(angle));
            if(corner||i) line(glm::vec3(previous,z),glm::vec3(point,z),edge);
            else first=point;
            previous=point;
        }
    }
    line(glm::vec3(previous,z),glm::vec3(first,z),edge);
}
inline constexpr float focusInset=.004F;
inline constexpr double pressSeconds=.16;
}
