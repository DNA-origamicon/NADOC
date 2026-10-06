#pragma once
#include "sidebar_menu.hpp"
#include "trajectory.hpp"
#include <sstream>

namespace nadoc_vr {
// Playback uses the same placement, input focus, drawing and hit regions as
// every other sidebar panel. Browser-owned trajectory requests remain unchanged.
class TrajectoryPanel {
 public:
    bool active=false;
    size_t savedOffset=0;
    void enter(std::array<SidebarMenu,2>& menus,const TrajectoryState& state) {
        auto& menu=menus[0];
        if(!active)savedOffset=menu.offsets[menu.selected];
        active=true;menu.open=true;menu.offsets[menu.selected]=0;
        menu.focus.reset();menu.hovered.clear();
        refresh(menus,state);
    }
    void exit(std::array<SidebarMenu,2>& menus) {
        if(!active)return;
        active=false;
        auto& menu=menus[0];menu.customTab.reset();
        menu.offsets[menu.selected]=savedOffset;
        menu.focus.reset();menu.hovered.clear();
    }
    void refresh(std::array<SidebarMenu,2>& menus,const TrajectoryState& state) const {
        if(!active)return;
        const bool available=state.active && state.frameCount>0;
        SidebarTab tab{0,"trajectory","Trajectory",{}};
        auto row=[&](std::string id,std::string label,std::string detail,bool enabled) {
            id="trajectory:"+id;
            tab.rows.push_back({id,std::move(label),std::move(detail),enabled?id:"",{}});
        };
        row("back","Trajectory - Return","SIMULATIONS",true);
        row("play",state.playing?"Pause":"Play",available?"":"NO ACTIVE TRAJECTORY",available);
        row("seek","Frame "+std::to_string(available?state.frameIndex+1:0)+" / "+std::to_string(state.frameCount),
            "HOLD TRIGGER / SLIDE TO SEEK",available);
        row("previous","Previous frame","",available);
        row("next","Next frame","",available);
        std::ostringstream rate;rate<<"Speed "<<state.speed<<"x / Stride "<<state.stride;
        row("status",rate.str(),state.live?"LIVE SOURCE":state.loop?"LOOP ON":"LOOP OFF",false);
        menus[0].customTab=std::move(tab);
    }
    static std::optional<uint32_t> frameAt(const HandPose& hand,const SidebarMenu& menu,
                                         const TrajectoryState& state) {
        if(!hand.valid || !menu.open || !menu.customTab || menu.tab().key!="trajectory" ||
           !state.active || state.frameCount==0)return std::nullopt;
        const auto bounds=menu.bounds();
        const auto local=menu.placement.rayPanelLocalPoint(hand,bounds.minimum,bounds.maximum);
        if(!local)return std::nullopt;
        const auto controls=menu.controls(false);
        const auto seek=std::find_if(controls.begin(),controls.end(),[](const auto& c){return c.id=="trajectory:seek";});
        if(seek==controls.end() || !seek->enabled || local->y<seek->bounds.minimum.y ||
           local->y>seek->bounds.maximum.y)return std::nullopt;
        const float fraction=std::clamp((local->x-seek->bounds.minimum.x)/
            (seek->bounds.maximum.x-seek->bounds.minimum.x),0.F,1.F);
        return uint32_t(std::round(double(fraction)*(state.frameCount-1)));
    }
};
}
