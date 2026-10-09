#include "move_panel.hpp"
#include <cassert>
#include <iostream>
int main() {
    using namespace nadoc_vr;
    // Authored axes and nm units survive desktop export rotation and room scaling.
    for(const auto basis:{glm::mat3(1),glm::mat3_cast(glm::quat(glm::vec3(.7F,-1.1F,.4F)))}) {
        SceneManipulator scene;
        scene.placeAtRoomOrigin({0,1.7F,1.5F},glm::quat(glm::vec3(.3F,.8F,-.2F)),
            glm::mat4(1),{0,0,-1.3F},basis);
        const auto model=scene.transform();
        const glm::vec3 pivot(.3F,1.1F,-.2F),point(.1F,-.2F,-1.1F),translation(.07F,-.03F,.11F);
        const auto world=glm::vec3(model*glm::vec4(point,1));
        HandPose start;start.valid=true;start.position=pivot+glm::vec3(.05F,.02F,.3F);
        start.orientation=glm::quat(glm::vec3(.1F,-.4F,.2F));
        MovePanel move;move.configure(glm::vec3(glm::inverse(model)*glm::vec4(pivot,1)),basis,.01F);
        move.grabPoint=pivot;move.begin(1,start,model,pivot);
        auto end=start;end.position+=translation;move.update(end);
        assert(glm::length(move.rotationDegrees)==0);
        assert(glm::distance(glm::vec3(model*move.transform()*glm::vec4(point,1)),world+translation)<2e-5F);
        const auto moved=glm::vec3(model*move.transform()*glm::vec4(point,1));
        const auto turn=glm::angleAxis(.7F,glm::normalize(glm::vec3(1,2,3)));
        move.begin(1,end,model,pivot,true);
        end.orientation=turn*end.orientation;end.position+=glm::vec3(1);move.update(end);
        assert(glm::distance(glm::vec3(model*move.transform()*glm::vec4(point,1)),pivot+(moved-world)+turn*(world-pivot))<3e-5F);
    }
    MovePanel panel;HandPose hand;hand.valid=true;
    panel.configure({},glm::mat3(1),1);panel.snap=true;
    panel.begin(1,hand,glm::mat4(1),{},true);
    hand.orientation=glm::angleAxis(glm::radians(22.F),glm::vec3(0,0,1));panel.update(hand);
    assert(std::abs(panel.rotationDegrees.z-15)<1e-5F);
    panel.adjust(5,1);assert(panel.rotationDegrees.z==16); // Snap does not change 1-degree manual detents.
    panel.hand.reset();panel.begin(1,hand,glm::mat4(1),{});
    hand.position={1.23456F,-.0001F,0};panel.update(hand);
    assert(panel.positionNm.x==1.235F && panel.positionNm.y==0);
    assert(MovePanel::number(-.0001F,3)=="0.000");
    std::array<SidebarMenu,2> menus{SidebarMenu(0),SidebarMenu(1)};
    panel.reset();panel.enter(menus);panel.refresh(menus,"cluster","READY");
    auto control=[&](const std::string& id) {
        auto controls=menus[1].controls();
        auto it=std::find_if(controls.begin(),controls.end(),[&](auto c){return c.id=="move:"+id;});
        assert(it!=controls.end());return *it;
    };
    assert(panel.selectionEnabled(0) && !panel.selectionEnabled(1));
    panel.selecting=true;assert(panel.selectionEnabled(1));
    for(const auto id:{"selection","snap","undo","redo","0:value","5:value"})control(id);
    assert(control("cancel").bounds.maximum.x<control("apply").bounds.minimum.x);
    assert(control("cancel").bounds.minimum.y==control("apply").bounds.minimum.y);
    assert(ui_style::buttonAccent("move:apply").g>ui_style::buttonAccent("move:apply").r);
    menus[1].draw([](auto,auto,auto){},[](auto,auto){});
    std::cerr<<menus[1].audit.summary()<<'\n';assert(menus[1].audit.valid());
    panel.begin(0,hand,glm::mat4(1),{});assert(!panel.hand);
    panel.begin(1,hand,glm::mat4(1),{});assert(panel.hand==1);
    assert(!panel.selectionEnabled(0) && !panel.selectionEnabled(1));
    panel.exit(menus);assert(panel.selectionEnabled(0) && panel.selectionEnabled(1));
}
