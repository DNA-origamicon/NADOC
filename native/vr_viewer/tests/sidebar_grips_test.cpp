#include "sidebar_grips.hpp"
#include <stdexcept>
#include <iostream>
using namespace nadoc_vr;
int main() {
    auto require=[](bool ok,const char* why){if(!ok)throw std::runtime_error(why);};
    std::array<SidebarMenu,2> menus{SidebarMenu(0),SidebarMenu(1)};
    for(size_t i=0;i<2;++i) {
        menus[i].open=true;
        menus[i].placement.openDocked({i==0?-.34F:.34F,0,-1},{1,0,0,0});
        (void)menus[i].placement.adjustScale(-1);
    }
    std::array<HandPose,2> hands{};
    int pulses=0;
    auto update=[&](std::array<bool,2> clicks){return updateSidebarGrips(menus,hands,clicks,[&](size_t,float){++pulses;});};
    // Both borders are within grab distance: the closer right border must win.
    hands[1]={true,false,menus[1].placement.worldPoint({kSidebarBounds.minimum.x,0,0}),{1,0,0,0}};
    update({false,false});
    require(menus[1].gripNearby[1]&&!menus[0].gripNearby[1],"Near highlight chose farther border");
    hands[1].pressed=true;auto used=update({false,true});
    require(used[1]&&menus[1].placement.dragHand()==1&&!menus[0].placement.dragHand(),"Grip chose farther panel");
    const auto before=menus[1].placement.position();
    hands[1].position+=glm::vec3(.1F,.05F,0);update({false,false});
    require(glm::length(menus[1].placement.position()-before-glm::vec3(.1F,.05F,0))<1e-5F,"Held border failed to move panel");
    require(menus[1].gripState==GripFrameState::moving&&pulses==1,"Missing move feedback");
    hands[0]={true,true,menus[1].placement.worldPoint({kSidebarBounds.maximum.x,0,0}),{1,0,0,0}};
    used=update({true,false});
    require(used[0]&&used[1]&&menus[1].placement.resizeActive()&&pulses==3,"Second grip failed to resize");
    const auto midpoint=(hands[0].position+hands[1].position)*.5F;
    const auto scale=menus[1].placement.scale();
    for(auto& hand:hands) hand.position=midpoint+(hand.position-midpoint)*1.2F;
    update({false,false});
    require(std::abs(menus[1].placement.scale()-scale*1.2F)<1e-5F,"Resize ratio incorrect");
    hands[0].pressed=false;hands[1].pressed=false;used=update({false,false});
    require(!used[0]&&!used[1]&&!menus[1].placement.resizeActive(),"Released frame retained ownership");
    // No scene-wide grab region: panel interior and invalid tracking cannot grab.
    hands[1]={true,true,menus[1].placement.position(),{1,0,0,0}};
    require(!update({false,true})[1],"Interior became a border target");
    hands[1].valid=false;require(!update({false,true})[1],"Invalid hand grabbed frame");
    // Visible rails must fit the enlarged frame and leave all existing controls clear.
    drawGripFrame(kSidebarBounds,GripFrameState::idle,
        [&](glm::vec3 a,glm::vec3 b,glm::vec3){
            require(menuLayoutContains(kSidebarBounds,{{std::min(a.x,b.x),std::min(a.y,b.y)},{std::max(a.x,b.x),std::max(a.y,b.y)}}),"Grip decoration outside rendered surface");
        },[&](MenuPanelBounds b,glm::vec3){require(menuLayoutContains(kSidebarBounds,b),"Rail fill clipped");},.04F);
    std::cout<<"Nearest border, movement, resize, release and frame bounds passed\n";
}
