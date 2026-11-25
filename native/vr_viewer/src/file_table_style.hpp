#pragma once
#include <array>
#include <string>
#include <algorithm>
#include <glm/glm.hpp>

// Approved gallery option 4: shared, literal geometry and solid-mesh styling.
namespace file_table_style {
struct Rect {float x,y,w,h;};
inline constexpr Rect panel{-.79F,-.67F,1.58F,1.32F};
inline constexpr Rect location{-.33F,.305F,.97F,.065F};
inline constexpr Rect rail{.68F,-.265F,.06F,.487F};
inline constexpr Rect command(size_t i){return {-.73F,.265F-float(i)*.125F,.32F,.095F};}
inline constexpr Rect row(size_t i){return {-.33F,.15F-float(i)*.083F,.97F,.072F};}
inline constexpr float scale=1.5F,faceDepth=.014F,textDepth=.030F;
inline const glm::vec3 ink{.9F,.94F,1},muted{.55F,.66F,.77F},accent{.35F,.76F,1},gold{.95F,.70F,.30F};
inline std::string fit(const std::string& label,float width,float size){
    const size_t count=size_t(std::max(0.F,(width/size+1.F)/6.F));
    return label.size()<=count?label:count>3?label.substr(0,count-3)+"...":label.substr(0,count);
}
template<class Ui> void surface(Ui& ui,Rect r,bool enabled,bool hover,bool selected){
    const auto tint=!enabled?glm::vec3(.24F,.29F,.34F):selected?glm::vec3(.15F,.38F,.48F):glm::vec3(.12F,.20F,.28F);
    const auto edge=hover?gold:selected?accent:glm::vec3(.30F,.43F,.55F);
    ui.rounded(r.x,r.y,r.w,r.h,.009F,edge,.012F);
    ui.rounded(r.x+.003F,r.y+.003F,r.w-.006F,r.h-.006F,.007F,tint,faceDepth);
}
template<class Ui> void control(Ui& ui,Rect r,const std::string& label,bool enabled,bool hover,bool selected,bool entry=false,
        std::array<std::string,3> detail={"--","--","--"}){
    surface(ui,r,enabled,hover,selected);
    const float font=entry?.0031F:.0034F;
    ui.text(fit(label,entry?.395F:r.w-.03F,font),r.x+.015F,r.y+r.h*.60F,font,enabled?ink:muted,textDepth);
    if(entry){
        constexpr std::array<float,3> offsets{.41F,.5276F,.662F};
        constexpr std::array<float,3> widths{.1176F,.1344F,.293F};
        // Preserve full dates in routing metadata; display YY-MM-DD in the approved column.
        if(detail[1].size()==10 && detail[1][4]=='-' && detail[1][7]=='-')detail[1]=detail[1].substr(2);
        for(size_t i=0;i<3;++i)ui.text(fit(detail[i],widths[i],.0028F),r.x+offsets[i],r.y+.043F,.0028F,muted,textDepth);
    }
}
template<class Ui> void headings(Ui& ui){
    ui.text("NAME                 TYPE   MODIFIED   SIZE",-.31F,.255F,.0028F,muted);
}
template<class Ui> void background(Ui& ui){ui.rect(panel.x,panel.y,panel.w,panel.h,{.035F,.048F,.067F},0);}
}
