#pragma once
// Included after SidebarControl, inside nadoc_vr. Backgrounds are never hit
// targets: each row/action retains the production layout and clipping contract.
template<class Line,class Fill>
void drawSidebarSets(const std::vector<SidebarControl>& controls,Line line,Fill fill) {
    std::optional<MenuPanelBounds> dimensions,sweep,jobs,history;
    auto extend=[](auto& group,const MenuPanelBounds& b){if(!group)group=b;else {group->minimum=glm::min(group->minimum,b.minimum);group->maximum=glm::max(group->maximum,b.maximum);}};
    for(const auto& c:controls){
        if(c.id.starts_with("dimension:select:") || c.id.starts_with("dimension:value:") || c.id.starts_with("dimension:visibility:") || c.id.starts_with("dimension:delete:")){
            auto b=c.bounds;if(c.viewport){b.minimum.y=c.viewport->minimum.y;b.maximum.y=c.viewport->maximum.y;}extend(dimensions,b);
        }
        if(c.id.starts_with("sweep:point:"))extend(sweep,c.viewport.value_or(c.bounds));
        if(c.id.starts_with("sim:j:"))extend(jobs,c.viewport.value_or(c.bounds));
        if(c.id.starts_with("history:row:"))extend(history,c.viewport.value_or(c.bounds));
    }
    for(auto* group:{&dimensions,&sweep,&jobs,&history})if(*group){auto b=**group;b.minimum-=glm::vec2(.005F);b.maximum+=glm::vec2(.005F);
        ui_style::rounded(b,{.027F,.041F,.055F},group==&dimensions?glm::vec3(.34F,.58F,.73F):glm::vec3(.18F,.29F,.35F),line,fill,.006F,.001F);}
    for(const auto& c:controls)if(c.id.starts_with("sweep:point:") || c.id.starts_with("history:row:")) {
        if(!c.viewport)continue;
        const auto b=c.drawingBounds.value_or(c.bounds);const auto v=*c.viewport;
        const float x=v.minimum.x+.012F,y=(b.minimum.y+b.maximum.y)*.5F;
        const auto color=c.active?glm::vec3(.38F,.85F,.68F):glm::vec3(.30F,.49F,.54F);
        line({x,v.minimum.y,.001F},{x,v.maximum.y,.001F},color*.65F);
        if(y>=v.minimum.y+.006F && y<=v.maximum.y-.006F)
            ui_style::rounded({{x-.006F,y-.006F},{x+.006F,y+.006F}},color,color,line,fill,.006F,.001F);
    }
}
