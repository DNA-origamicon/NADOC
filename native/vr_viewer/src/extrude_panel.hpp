#pragma once
#include "sidebar_menu.hpp"
namespace nadoc_vr {
inline int extrudeLengthStep(bool square,bool coarse) { return latticeBasePairPeriod(square)*(coarse?3:1); }
// Shared sidebar layout pins Confirm and Back below the scrolling settings.
class ExtrudePanel {
 public:
    bool active=false;
    size_t savedOffset=0;
    void enter(std::array<SidebarMenu,2>& menus) {
        if(!active) savedOffset=menus[1].offset();
        active=true;menus[1].open=true;menus[1].offsets[menus[1].selected]=0;
        menus[1].focus.reset();
    }
    void exit(std::array<SidebarMenu,2>& menus) {
        active=false;auto& m=menus[1];m.customTab.reset();m.offsets[m.selected]=savedOffset;
        m.focus.reset();m.hovered.clear();
    }
    void refresh(std::array<SidebarMenu,2>& menus,int length,int direction,
                 const std::string& plane,const std::string& strands,bool ligate,
                 size_t cells,bool square,bool placed,const std::string& status) const {
        if(!active)return;
        SidebarTab tab{1,"extrude","Extrude",{}};
        auto row=[&](std::string id,std::string label,std::string detail="") {
            tab.rows.push_back({"extrude:"+id,label,detail,"extrude:"+id,{}});
        };
        row("back","Extrude - Return to tools",status);
        row("confirm","CONFIRM",std::to_string(cells)+" HELICES / "+std::to_string(length)+" BP");
        row("cancel","CANCEL");
        row("less-period","-"+std::to_string(extrudeLengthStep(square,true))+" BP","LENGTH "+std::to_string(length)+" BP");
        row("less","-"+std::to_string(extrudeLengthStep(square,false))+" BP","LENGTH "+std::to_string(length)+" BP");
        row("direction","Direction",direction>0?"FORWARD":"REVERSE");
        row("plane",plane);
        row("lattice",square?"Lattice: Square":"Lattice: Honeycomb");
        row("strands","Strands: "+strands);
        row("ligate",ligate?"Ligate: Yes":"Ligate: No");
        row("paint","Show lattice painter");
        row("freeform",placed?"USE DEFAULT PLANE":"PLACE FREEFORM");
        row("recenter","Frame model");row("undo","UNDO");
        menus[1].customTab=std::move(tab);
    }
};
}
