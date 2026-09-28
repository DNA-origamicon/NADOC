#pragma once
#include "dimensions.hpp"
#include "sidebar_menu.hpp"
namespace nadoc_vr {
class DimensionPanel {
 public:
    Dimensions tool;
    std::array<bool,2> savedOpen{};
    size_t savedOffset=0;
    void exit(std::array<SidebarMenu,2>& menus) {
        tool.leave();menus[1].customTab.reset();menus[1].offsets[menus[1].selected]=savedOffset;
        for(size_t h=0;h<2;++h) {menus[h].open=savedOpen[h];menus[h].focus.reset();menus[h].hovered.clear();}
    }
    bool action(const std::string& action,std::array<SidebarMenu,2>& menus,float scale) {
        if(!action.starts_with("dimension:"))return false;
        if(action=="dimension:toggle" && tool.active) {exit(menus);return true;}
        if(action=="dimension:clear") {tool.entries.clear();tool.selected=0;refresh(menus,scale);return true;}
        if(!tool.active) {
            for(size_t h=0;h<2;++h) {savedOpen[h]=menus[h].open;menus[h].focus.reset();}
            savedOffset=menus[1].offset();menus[1].offsets[menus[1].selected]=0;
            menus[0].open=false;menus[1].open=true;tool.active=true;tool.create();
        } else if(action=="dimension:new")tool.create();
        else if(action.starts_with("dimension:select:"))tool.select(std::stoul(action.substr(17)));
        else if(action.starts_with("dimension:delete:"))tool.remove(std::stoul(action.substr(17)));
        else if(action.starts_with("dimension:visibility:")) {
            unsigned id=std::stoul(action.substr(21));
            for(auto& e:tool.entries)if(e.id==id)e.visible=!e.visible;
        }
        refresh(menus,scale);
        if(action=="dimension:new" || action=="dimension:toggle") {
            auto& m=menus[1];
            m.offsets[m.selected]=tool.entries.empty()?0:(tool.entries.size()-1)/m.pageRows()*m.pageRows();
        }
        return true;
    }
    template<class Feedback>
    void input(const std::array<HandPose,2>& hands,const glm::mat4& model,bool manipulating,
            const std::array<bool,2>& clicked,std::array<bool,2>& blocked,
            std::array<std::string,2>& owners,std::array<SidebarMenu,2>& menus,float scale,Feedback feedback) {
        if(!tool.active)return;
        tool.update(hands,model,manipulating);
        for(size_t h=0;h<2;++h) {
            if(!blocked[h]) {
                owners[h]="dimension";
                if(clicked[h] && hands[h].valid) {tool.trigger(h);feedback(h);}
            }
            blocked[h]=true;
        }
        refresh(menus,scale);
    }
    void refresh(std::array<SidebarMenu,2>& menus,float scale) {
        if(!tool.active)return;
        SidebarTab tab{1,"dimensions","Dimensions",{
            {"dimension:toggle","Dimensions - Return to menus",tool.persistenceConnected?(tool.savePending?"SAVING DIMENSIONS":"PLACED DIMENSIONS SAVED"):"VIEWER SESSION ONLY","dimension:toggle",{}},
            {"dimension:new","+ New dimension","","dimension:new",{}},
            {"dimension:clear","Clear all dimensions","","dimension:clear",{}}}};
        for(const auto& e:tool.entries) {
            auto id="dimension:select:"+std::to_string(e.id);
            tab.rows.push_back({id,(e.id==tool.selected?"> ":"")+(e.name.empty()?"Dimension "+std::to_string(e.id):e.name)+" / "+Dimensions::label(e,scale),e.visible?"eye":"eye-off",id,{}});
        }
        auto& m=menus[1];m.customTab=std::move(tab);
        m.offsets[m.selected]=std::min(m.offset(),m.total()==0?0:(m.total()-1)/m.pageRows()*m.pageRows());
        if(m.focus.active) {
            const auto controls=m.controls();
            if(std::none_of(controls.begin(),controls.end(),[&](const auto& c){return c.id==m.focus.id;}))m.focus.id=controls.front().id;
        }
    }
};
}
