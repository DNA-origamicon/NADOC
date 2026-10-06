#pragma once
#include "menu_layout.hpp"

namespace nadoc_vr {

// Old detailed menus share the same readable-text floor and reserved columns
// as the sidebar. The caller supplies a right rail for two-column value rows.
template<class Draw>
void drawLegacyMenuText(MenuLayoutAudit& audit,MenuPanelBounds panel,
        const std::string& value,float x,float y,float maximumScale,glm::vec3 color,
        Draw draw,std::optional<float> rightRail=std::nullopt) {
    MenuPanelBounds content{panel.minimum+glm::vec2(.055F),panel.maximum-glm::vec2(.055F)};
    if(rightRail)content.maximum.x=std::min(content.maximum.x,*rightRail);
    x=std::clamp(x,content.minimum.x,content.maximum.x);
    const auto label=boundedMenuStrokeText(value,content.maximum.x-x,maximumScale);
    audit.addText("panel:"+value,label.text,x,y,label.scale,content);
    if(!label.text.empty())draw(label.text,x,y,label.scale,color);
}

// Complete the audit even when an individual legacy page returns early.
struct FinishMenuLayout {
    MenuLayoutAudit& audit;
    ~FinishMenuLayout(){audit.finish();}
};

inline void auditLegacyMenuFrame(MenuLayoutAudit& audit,MenuPanelBounds panel) {
    constexpr float rail=.025F;
    const auto lo=panel.minimum,hi=panel.maximum;
    audit.addFeature("frame:left",{lo,{lo.x+rail,hi.y}});
    audit.addFeature("frame:right",{{hi.x-rail,lo.y},hi});
    audit.addFeature("frame:bottom",{lo,{hi.x,lo.y+rail}});
    audit.addFeature("frame:top",{{lo.x,hi.y-rail},hi});
}
}
