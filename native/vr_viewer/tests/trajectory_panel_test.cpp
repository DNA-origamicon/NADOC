#include "trajectory_panel.hpp"
#include <cassert>
#include <iostream>

int main() {
    using namespace nadoc_vr;
    std::array<SidebarMenu,2> menus{SidebarMenu(0),SidebarMenu(1)};
    auto& menu=menus[0];
    const auto originalTab=menu.tab().key;
    menu.offsets[menu.selected]=8;
    menu.focus.begin("previous-control","");
    TrajectoryPanel panel;
    TrajectoryState state;
    panel.enter(menus,state);
    assert(panel.active && menu.open && menu.tab().key=="trajectory" && !menu.focus.active);
    assert(menu.offset()==0 && !menus[1].open);
    auto control=[&](const std::string& id) {
        const auto controls=menu.controls(false);
        const auto found=std::find_if(controls.begin(),controls.end(),[&](const auto& c){return c.id==id;});
        assert(found!=controls.end());return *found;
    };
    assert(menu.activate(control("trajectory:back"))=="trajectory:back");
    for(const auto* id:{"trajectory:play","trajectory:seek","trajectory:previous","trajectory:next"}) {
        assert(!control(id).enabled && menu.activate(control(id)).empty());
    }
    state.active=true;state.frameCount=11;state.frameIndex=5;state.playing=true;
    panel.refresh(menus,state);
    assert(control("trajectory:play").label=="Pause");
    assert(control("trajectory:seek").label=="Frame 6 / 11");
    for(const auto* id:{"trajectory:play","trajectory:seek","trajectory:previous","trajectory:next"})
        assert(control(id).enabled && menu.activate(control(id))==id);
    assert(!control("trajectory:status").enabled);
    const auto facing=glm::angleAxis(.35F,glm::vec3(0,1,0));
    menu.placement.openDocked({.2F,.1F,-1.2F},facing);menu.placement.setScale(.8F);
    const auto seek=control("trajectory:seek").bounds;
    HandPose hand;hand.valid=true;hand.orientation=facing;
    auto aim=[&](float x,float y) {hand.position=menu.placement.worldPoint({x,y,.4F});};
    const float middleY=(seek.minimum.y+seek.maximum.y)*.5F;
    for(const auto [fraction,frame]:std::array<std::pair<float,uint32_t>,3>{{{0,0},{.5F,5},{1,10}}}) {
        aim(seek.minimum.x+fraction*(seek.maximum.x-seek.minimum.x),middleY);
        assert(TrajectoryPanel::frameAt(hand,menu,state)==frame);
    }
    aim(seek.minimum.x-.01F,middleY);assert(TrajectoryPanel::frameAt(hand,menu,state)==0);
    aim(seek.maximum.x+.01F,middleY);assert(TrajectoryPanel::frameAt(hand,menu,state)==10);
    aim(0,seek.maximum.y+.02F);assert(!TrajectoryPanel::frameAt(hand,menu,state));
    aim(0,middleY);hand.valid=false;assert(!TrajectoryPanel::frameAt(hand,menu,state));
    hand.valid=true;menu.open=false;assert(!TrajectoryPanel::frameAt(hand,menu,state));
    menu.open=true;state.active=false;assert(!TrajectoryPanel::frameAt(hand,menu,state));
    state.active=true;state.frameCount=0;assert(!TrajectoryPanel::frameAt(hand,menu,state));
    state.frameCount=1;assert(TrajectoryPanel::frameAt(hand,menu,state)==0);
    state.frameCount=4294967295U;state.frameIndex=4294967294U;
    panel.refresh(menus,state);aim(seek.maximum.x,middleY);
    assert(TrajectoryPanel::frameAt(hand,menu,state)==4294967294U);
    assert(control("trajectory:seek").label=="Frame 4294967295 / 4294967295");
    menu.draw([](glm::vec3,glm::vec3,glm::vec3){},[](MenuPanelBounds,glm::vec3){});
    assert(menu.audit.valid());
    panel.enter(menus,state); // Repeated opening must retain the original offset.
    panel.exit(menus);
    assert(!panel.active && !menu.customTab && menu.tab().key==originalTab && menu.offset()==8);
    assert(!TrajectoryPanel::frameAt(hand,menu,state));
    std::cout<<"Trajectory sidebar controls, seek bounds and restoration passed\n";
}
