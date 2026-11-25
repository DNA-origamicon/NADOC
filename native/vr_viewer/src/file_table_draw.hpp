#pragma once
#include "file_table_style.hpp"
// Same solid surfaces, glyph geometry and spacing as FileGallery option 4.
inline void drawFileTableControl(SolidUi& ui,const nadoc_vr::SidebarControl& c,bool hover){
    const auto b=c.bounds;const auto d=nadoc_vr::fileTableCells(c);
    file_table_style::control(ui,{b.minimum.x,b.minimum.y,b.maximum.x-b.minimum.x,b.maximum.y-b.minimum.y},c.label,
        c.enabled||c.id=="routing-help",hover,c.active,nadoc_vr::fileTableEntry(c.id),{d[1],d[2],d[3]});
}
inline void drawFileTable(SolidUi& ui,const nadoc_vr::SidebarMenu& menu){
    using namespace file_table_style;
    background(ui);
    ui.text("FILE",-.73F,.595F,.0049F,ink);
    ui.text("NAME / TYPE / MODIFIED / SIZE",-.73F,.535F,.0033F,muted);
    ui.text("FILE",-.73F,.39F,.0038F,muted);
    headings(ui);
    for(const auto& c:menu.controls()){
        if(c.id=="scrollbar"){
            surface(ui,rail,true,menu.hovered==c.id,false);
            const auto b=menu.scrollThumb();ui.rounded(b.minimum.x,b.minimum.y,b.maximum.x-b.minimum.x,b.maximum.y-b.minimum.y,.009F,accent,.020F);
        }else drawFileTableControl(ui,c,menu.hovered==c.id||(menu.focus.active&&menu.focus.id==c.id));
    }
    if(!menu.total())ui.text("NO FILES IN THIS FOLDER",-.315F,.18F,.0031F,muted,textDepth);
    ui.text(std::to_string(menu.total()?menu.offset()+1:0)+"-"+std::to_string(std::min(menu.offset()+menu.pageRows(),menu.total()))+" / "+std::to_string(menu.total())+" FILES",-.33F,-.59F,.0034F,accent);
}
