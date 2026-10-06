#pragma once
#include "lattice_view.hpp"
#include "menu_grip_frame.hpp"

namespace nadoc_vr {
struct LatticePainterChrome {
    std::string plane;
    bool square=false, scaling=false, exitHovered=false;
    size_t selected=0, existing=0;
    GripFrameState grip=GripFrameState::idle;
    bool contextResolved=true;
};

// The same geometry feeds the cached frosted surface and the layout audit.
template<class Line,class Fill,class Text>
MenuLayoutAudit drawLatticePainterChrome(const LatticePainterChrome& state,
        Line line,Fill fill,Text text) {
    MenuLayoutAudit audit;
    audit.reset(kLatticePainterContent);
    drawGripFrame(kLatticePainterBounds,state.grip,line,fill);
    auto label=[&](const std::string& id,const std::string& value,
                   MenuPanelBounds bounds,float y,float maximum,glm::vec3 color) {
        const float scale=fittedStrokeTextScale(value.size(),maximum,
            bounds.maximum.x-bounds.minimum.x-.024F);
        const float x=(bounds.minimum.x+bounds.maximum.x-strokeTextWidth(value.size(),scale))*.5F;
        audit.addText(id,value,x,y,scale,bounds);
        text(value,x,y,scale,color);
    };
    const auto content=kLatticePainterContent;
    label("title","LATTICE PAINTER",content,.261F,.0034F,ui_style::text);
    label("plane",std::string(state.square?"SQUARE / ":"HONEYCOMB / ")+state.plane,
        content,.230F,.0028F,{.65F,.88F,1});
    label("help",state.scaling?"SCALING LATTICE":"TWO GRIPS: ZOOM / BORDER: MOVE OR RESIZE",
        content,.199F,.0021F,state.scaling?glm::vec3(.4F,1,.6F):ui_style::disabledText);
    line({content.minimum.x,.181F,0},{content.maximum.x,.181F,0},ui_style::border);
    line({content.minimum.x,-.162F,0},{content.maximum.x,-.162F,0},ui_style::border);
    label("counts",std::to_string(state.selected)+" SELECTED / "+(state.contextResolved ? std::to_string(state.existing)+" EXISTING" : "SOURCE UNRESOLVED"),
        content,-.174F,.0024F,ui_style::focus);
    label("forward","FWD BLUE",{{-.251F,-.216F},{-.09F,-.190F}},-.198F,.0023F,{41.F/255,182.F/255,246.F/255});
    label("reverse","REV RED",{{-.08F,-.216F},{.07F,-.190F}},-.198F,.0023F,{239.F/255,83.F/255,80.F/255});
    label("occupied","EXISTING",{{.08F,-.216F},{.251F,-.190F}},-.198F,.0023F,{.7F,.76F,.83F});
    for(const auto& [id,bounds]:std::array<std::pair<const char*,MenuPanelBounds>,2>{{
            {"CENTER PAINT",kCenterPaintBounds},{"EXIT",kLatticePainterExit}}}) {
        const auto color=std::string(id)=="EXIT"
            ?(state.exitHovered?ui_style::focus:ui_style::danger):ui_style::accent;
        ui_style::rounded(bounds,glm::mix(glm::vec3(.075F),color,.045F),color,line,fill,.008F);
        audit.addControl(id,bounds,bounds);
        label(id,id,bounds,-.235F,.0026F,color);
    }
    audit.addControl("grid",kLatticePainterGrid,kLatticePainterGrid);
    return audit;
}
}
