#include "dimension_panel.hpp"
#include <stdexcept>
#include <iostream>
using namespace nadoc_vr;
int main() {
    auto require=[](bool value,const char* message){if(!value)throw std::runtime_error(message);};
    DimensionPanel panel;
    std::array<SidebarMenu,2> menus{SidebarMenu(0),SidebarMenu(1)};
    menus[0].open=menus[1].open=true;menus[1].offsets[menus[1].selected]=8;
    panel.action("dimension:toggle",menus,.01F);
    require(!menus[0].open && menus[1].open && menus[1].customTab.has_value(),"Focused panel did not isolate menus");
    std::array<HandPose,2> hands{{{true,false,{-.2F,0,0},{1,0,0,0}},{true,false,{.2F,0,0},{1,0,0,0}}}};
    auto& d=panel.tool;const glm::mat4 identity(1);
    d.update(hands,identity,false);
    require(std::abs(Dimensions::length(*d.current(),.01F)-40)<.001F,"Incorrect nanometers");
    d.trigger(0);auto pinned=d.current()->points[0];hands[0].position.x-=.1F;hands[1].position.x+=.1F;d.update(hands,identity,false);
    require(d.current()->points[0]==pinned && std::abs(Dimensions::length(*d.current(),.01F)-50)<.001F,"Pin or live length failed");
    d.trigger(0);d.update(hands,identity,false);require(d.current()->points[0]!=pinned,"Recall failed");
    auto old=d.current()->points;d.update(hands,glm::scale(glm::translate(identity,{1,2,3}),glm::vec3(2)),true);
    require(d.current()->points==old && !d.current()->attached[0],"Model grip changed model coordinates");
    panel.action("dimension:new",menus,.01F);require(d.entries.size()==2 && !d.entries[0].attached[1],"New line failed to freeze previous");
    d.update(hands,identity,false);hands[0].valid=false;auto point=d.current()->points[0];hands[0].position={9,9,9};d.update(hands,identity,false);require(d.current()->points[0]==point,"Tracking loss corrupted endpoint");
    panel.action("dimension:visibility:1",menus,.01F);require(!d.entries[0].visible,"Eye control failed");
    panel.refresh(menus,.01F);
    menus[1].draw([](glm::vec3,glm::vec3,glm::vec3){},[](MenuPanelBounds,glm::vec3){});
    require(menus[1].audit.valid(),menus[1].audit.summary().c_str());
    for(auto& c:menus[1].controls())require(!c.id.starts_with("tab:"),"Full tabs remain");
    panel.action("dimension:delete:1",menus,.01F);require(d.entries.size()==1,"Delete failed");
    for(int i=0;i<10;++i)panel.action("dimension:new",menus,.01F);
    menus[1].offsets[menus[1].selected]=0;
    menus[1].focus.begin("scrollbar","");menus[1].navigate({0,-1});
    require(menus[1].offset()==1,"Dimension list did not scroll one row with pad");
    menus[1].draw([](glm::vec3,glm::vec3,glm::vec3){},[](MenuPanelBounds,glm::vec3){});
    require(menus[1].audit.valid(),menus[1].audit.summary().c_str());
    menus[1].navigate({0,1});require(menus[1].offset()==0,"Dimension scrollbar could not scroll back");
    panel.exit(menus);require(menus[0].open && menus[1].open && !menus[1].customTab && menus[1].offset()==8 && !d.current()->attached[1],"Exit did not restore and freeze");
    panel.action("dimension:toggle",menus,.01F);panel.action("dimension:toggle",menus,.01F);require(!d.active && menus[0].open,"Main button did not exit");
    std::cout<<"Dimensions pin, recall, tracking, model transform, entry actions and restoration passed\n";
}
