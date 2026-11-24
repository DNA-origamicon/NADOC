#pragma once
#include "keyboard_slate.hpp"
inline void drawTextKeyboardControl(SolidUi& ui,const nadoc_vr::SidebarMenu& menu,const nadoc_vr::SidebarControl& c){
    const auto b=c.bounds;const auto size=b.maximum-b.minimum;
    if(c.action.empty()){
        ui.rounded(b.minimum.x,b.minimum.y,size.x,size.y,.012F,{.06F,.09F,.13F},.006F);
        const auto text=c.label.size()>55?"..."+c.label.substr(c.label.size()-52):c.label;
        ui.text(text,b.minimum.x+.025F,b.maximum.y-.035F,.0047F,{.9F,.94F,1},.012F);
        return;
    }
    keyboard_slate::key(ui,b.minimum.x,b.minimum.y,size.x,size.y,c.label,menu.keyboardEnabled(c),
        menu.hovered==c.id||(menu.focus.active&&menu.focus.id==c.id),menu.isActive(c.action),menu.keyPressure(c),c.id.ends_with("-delete"));
}
inline void drawTextKeyboard(SolidUi& ui,const nadoc_vr::SidebarMenu& menu){
    const auto b=menu.bounds();ui.rect(b.minimum.x,b.minimum.y,b.maximum.x-b.minimum.x,b.maximum.y-b.minimum.y,{.035F,.048F,.067F},0);
    nadoc_vr::drawGripFrame(b,menu.gripState,
        [&](glm::vec3 a,glm::vec3 z,glm::vec3 color){
            constexpr float width=.002F;
            ui.rect(std::min(a.x,z.x)-width*.5F,std::min(a.y,z.y)-width*.5F,
                std::abs(z.x-a.x)+width,std::abs(z.y-a.y)+width,color,.009F);
        },[&](nadoc_vr::MenuPanelBounds rail,glm::vec3 color){
            ui.rect(rail.minimum.x,rail.minimum.y,rail.maximum.x-rail.minimum.x,rail.maximum.y-rail.minimum.y,color,.006F);
        },nadoc_vr::ui_style::gripRail);
    const std::string hint="BORDER: HOLD TO MOVE / DOUBLE TO RESIZE";
    ui.text(hint,-float(hint.size()*6-1)*.0026F*.5F,.689F,.0026F,{.55F,.66F,.77F},.012F);
    ui.text(menu.tab().label,-.86F,.665F,.0044F,{.9F,.94F,1});
    ui.text("POINT AND TRIGGER TO TYPE",-.86F,.59F,.0028F,{.55F,.66F,.77F});
    for(const auto& c:menu.controls())drawTextKeyboardControl(ui,menu,c);
}
