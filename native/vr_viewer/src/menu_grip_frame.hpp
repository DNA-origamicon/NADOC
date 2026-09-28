#pragma once
#include "ui_style.hpp"

namespace nadoc_vr {
enum class GripFrameState { idle, ready, moving, resizing };
inline const char* gripFrameName(GripFrameState state) {
    switch(state) {
        case GripFrameState::ready:return "ready";
        case GripFrameState::moving:return "moving";
        case GripFrameState::resizing:return "resizing";
        default:return "idle";
    }
}
// Continuous rails and corner grips, inside the very same bounds used to grab.
// The line-only adapter also gives older tool panels the shared frame treatment.
template<class Line,class Fill> void drawGripFrame(MenuPanelBounds b,GripFrameState state,
        Line line,Fill fill,float width=.025F) {
    const auto color=state==GripFrameState::moving?ui_style::focus:
        state==GripFrameState::resizing?glm::vec3(100,220,150)/255.F:
        state==GripFrameState::ready?ui_style::accent:glm::vec3(104,145,180)/255.F;
    const glm::vec2 lo=b.minimum,hi=b.maximum;
    fill({lo,{lo.x+width,hi.y}},color*.35F);
    fill({{hi.x-width,lo.y},hi},color*.35F);
    fill({lo,{hi.x,lo.y+width}},color*.35F);
    fill({{lo.x,hi.y-width},hi},color*.35F);
    for(float inset:{.002F,width}) {
        const glm::vec2 a=lo+glm::vec2(inset),z=hi-glm::vec2(inset);
        line({a.x,a.y,.001F},{z.x,a.y,.001F},color);
        line({z.x,a.y,.001F},{z.x,z.y,.001F},color);
        line({z.x,z.y,.001F},{a.x,z.y,.001F},color);
        line({a.x,z.y,.001F},{a.x,a.y,.001F},color);
    }
    // Four broad L-shaped corner handles. Texture supplies a non-color cue.
    for(float x:{lo.x,hi.x}) for(float y:{lo.y,hi.y}) {
        const float dx=x==lo.x?1.F:-1.F,dy=y==lo.y?1.F:-1.F;
        for(int i=0;i<3;++i) {
            const float inset=.007F+i*.007F;
            line({x+dx*inset,y+dy*.085F,.002F},{x+dx*inset,y+dy*inset,.002F},color);
            line({x+dx*inset,y+dy*inset,.002F},{x+dx*.085F,y+dy*inset,.002F},color);
        }
    }
    for(int i=-2;i<=2;++i) {
        const float y=(lo.y+hi.y)*.5F+i*.016F;
        line({lo.x+.007F,y,.002F},{lo.x+width-.007F,y,.002F},color);
        line({hi.x-width+.007F,y,.002F},{hi.x-.007F,y,.002F},color);
    }
}
}
