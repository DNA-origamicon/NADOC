#pragma once
// Same shallow beveled card treatment as the gallery, constrained to the
// production viewport even while the list is between scroll positions.
inline void drawJobCard(SolidUi& ui,const nadoc_vr::SidebarControl& c,bool hover,float depth) {
    const auto b=c.bounds;const auto size=b.maximum-b.minimum;
    const auto face=c.active?glm::vec3(.12F,.32F,.38F):hover?glm::vec3(.22F,.30F,.40F):glm::vec3(.10F,.145F,.19F);
    ui.bevel(b.minimum.x,b.minimum.y,size.x,size.y,.006F,.003F,depth,.003F,face);
    const auto ink=c.enabled?glm::vec3(.89F,.93F,.98F):glm::vec3(.53F,.64F,.75F);
    ui.rect(b.minimum.x+.005F,b.minimum.y+.006F,.004F,std::max(0.F,size.y-.012F),c.active?glm::vec3(.38F,.85F,.68F):glm::vec3(.82F,.62F,1.F),depth+.001F);
    const float scale=.004F,left=b.minimum.x+.022F,top=b.maximum.y-.016F;
    const auto lines=nadoc_vr::SidebarMenu::wrap(c.label,size_t((size.x-.045F)/(6*scale)));
    int index=0;
    for(const auto& text:lines){const float y=top-index++*.036F;if(y-.028F<b.minimum.y+.027F)break;ui.text(text,left,y,scale,ink,depth+.002F);}
    if(size.y>.07F && !c.section.empty()){
        const auto fitted=nadoc_vr::boundedMenuStrokeText(c.section,size.x-.045F,.003F);
        ui.text(fitted.text,left,b.minimum.y+.021F,fitted.scale,{.53F,.64F,.75F},depth+.002F);
    }
}
