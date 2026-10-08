#pragma once
#include "sidebar_menu.hpp"
#include "sweep_draft.hpp"
#include <iomanip>
#include <sstream>
#include <tuple>

namespace nadoc_vr {
inline std::string sweepNumber(float value) {
    std::ostringstream out;out<<std::fixed<<std::setprecision(1)<<(std::abs(value)<.05F?0.F:value);return out.str();
}
inline std::string sweepPositionNumber(float value) {
    const auto truncated=std::trunc(value*100.F)/100.F;
    std::ostringstream out;out<<std::fixed<<std::setprecision(2)<<(truncated==0?0:truncated);return out.str();
}
class SweepPanel {
 public:
    bool active=false;
    size_t savedOffset=0,lastSelected=std::numeric_limits<size_t>::max();
    int lastStep=0;
    void enter(std::array<SidebarMenu,2>& menus) {
        if(!active)savedOffset=menus[1].offset();
        active=true;lastSelected=std::numeric_limits<size_t>::max();lastStep=0;
        refreshState_.reset();
        auto& m=menus[1];m.open=true;m.offsets[m.selected]=0;m.rowScroll={};m.focus.reset();
    }
    void exit(std::array<SidebarMenu,2>& menus) {
        active=false;auto& m=menus[1];m.customTab.reset();m.offsets[m.selected]=savedOffset;
        m.rowScroll={};m.focus.reset();m.hovered.clear();
    }
    void refresh(std::array<SidebarMenu,2>& menus,const SweepDraft& draft,size_t cells,bool square,
        const std::string& strands,bool ligate,const std::string& status,const std::string& plane="XY",const std::string& totalBp="CALCULATING") {
        if(!active)return;
        const RefreshState state{draft.revision,draft.selected,cells,draft.step,square,ligate,
            draft.freeDrawArmed,draft.drawing,draft.smoothingStrength,strands,status,plane,totalBp};
        if(refreshState_==state && menus[1].customTab && menus[1].tab().key=="sweep")return;
        refreshState_=state;
        SidebarTab tab{1,"sweep",draft.step==1?"Sweep - Paint lattice":"Sweep - Define path",{}};
        auto row=[&](const std::string& id,const std::string& label,const std::string& detail="",const std::string& action="") {
            tab.rows.push_back({"sweep:"+id,label,detail,action.empty()?"sweep:"+id:action,{}});
        };
        row("back","BACK",status);
        row("confirm",draft.step==1?"NEXT":"CONFIRM",std::to_string(cells)+" HELICES");
        if(draft.step==1) {
            row("cancel","CANCEL","STEP 1 OF 2 - PAINT LATTICE");
            row("plane","SWEEP FROM "+plane);
            row("lattice",square?"Lattice: Square":"Lattice: Honeycomb");
            row("strands","Strands: "+strands);
            row("ligate",ligate?"Ligate: Yes":"Ligate: No");
            row("paint","Show lattice painter",std::to_string(cells)+" CELLS SELECTED");
            row("recenter","Frame model");row("undo","UNDO");
        } else {
            row("free-draw",draft.drawing?"DRAWING - RELEASE TO FINISH":draft.freeDrawArmed?"HOLD TRIGGER TO DRAW":"FREE DRAW",
                "STEP 2 OF 2 - XYZ OFFSETS IN NM");
            row("add-point","ADD POINT");row("delete-point","DELETE SELECTED");
            row("smoothing-less","-");row("smoothing","SMOOTH "+sweepNumber(draft.smoothingStrength)+"X");
            row("smoothing-more","+");
            row("bp-info","NEW BP: "+totalBp);
            for(size_t i=0;i<draft.pointsNm.size();++i) {
                const auto id=std::to_string(i);
                row("point:"+id,i==0?"ORIGIN - FIXED":"POINT "+id,i==draft.selected?"SELECTED":"");
                row("direction:"+id,draft.directionControlled(i)?"DIR ON":"DIR OFF");
                for(int axis=0;axis<3;++axis) {
                    const auto prefix="axis:"+id+":"+std::to_string(axis);
                    row(prefix+":value",(draft.directionControlled(i)?std::string("R")+"XYZ"[axis]:std::string(1,"XYZ"[axis]))+" "+(draft.directionControlled(i)?sweepNumber((*draft.orientations[i])[axis]):sweepPositionNumber(draft.pointsNm[i][axis])),"","sweep:point:"+id);
                    row(prefix+":-1","DOWN");row(prefix+":1","UP");
                }
            }
        }
        auto& m=menus[1];m.customTab=std::move(tab);
        if(lastStep!=draft.step){m.offsets[m.selected]=0;m.rowScroll={};m.focus.reset();}
        if(draft.step==2 && lastSelected!=draft.selected) {
            if(draft.selected<m.offset())m.offsets[m.selected]=draft.selected;
            else if(draft.selected>=m.offset()+m.pageRows())m.offsets[m.selected]=draft.selected-m.pageRows()+1;
            m.rowScroll={};
        }
        const size_t maxOffset=m.total()>m.pageRows()?m.total()-m.pageRows():0;
        m.offsets[m.selected]=std::min(m.offset(),maxOffset);
        lastSelected=draft.selected;lastStep=draft.step;
    }
 private:
    using RefreshState=std::tuple<uint64_t,size_t,size_t,int,bool,bool,bool,bool,float,
        std::string,std::string,std::string,std::string>;
    std::optional<RefreshState> refreshState_;
};
}
