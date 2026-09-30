#include "remote_panel.hpp"
#include "desktop_panel.hpp"
#include <iostream>
#include <stdexcept>
using namespace nadoc_vr;
void check(bool value,const char* message){if(!value)throw std::runtime_error(message);}
HandPose aim(glm::vec3 target) {
    HandPose h;h.valid=true;h.position={0,0,0};
    h.orientation=glm::rotation(glm::vec3(0,0,-1),glm::normalize(target));return h;
}
int main(){try {
    MenuPlacement p,front;RemotePanelControl control;
    const MenuPanelBounds b{{-1,-1},{1,1}};
    p.openDocked({0,0,-3},glm::quat(1,0,0,0));p.setScale(1);
    std::vector<RemotePanelTarget> targets{{&p,b,b}};
    std::array<HandPose,2> hands{};hands[1]=aim({.99F,0,-3});
    auto update=[&](bool click,bool held,double t){return control.update(targets,hands,{false,click},{false,held},{0,0,0},t);};
    check(update(true,true,1)[1]&&control.active==&p&&!control.resizing,"Distant border did not acquire move");
    const auto initial=p.position();
    hands[1].orientation=glm::angleAxis(.25F,glm::vec3(0,1,0))*hands[1].orientation;
    update(false,true,1.2);
    check(glm::distance(initial,p.position())>.5F,"Ray sweep did not move distant panel");
    check(std::abs(glm::length(p.position())-3)<1e-4F,"Move changed panel radius");
    check(p.remoteMode()==1,"Remote movement state missing");
    update(false,false,1.3);check(!control.active&&p.remoteMode()==0,"Release retained remote owner");
    hands[1]=aim(p.worldPoint({1.015F,0,0}));update(true,true,1.5);
    check(control.active==&p,"Small outside-border aim error was not tolerated");control.cancel();
    // Two taps on one border enter resize, without a delayed first click.
    hands[1]=aim(p.worldPoint({.99F,0,0}));update(true,true,2);update(false,false,2.05);update(true,true,2.15);
    check(control.resizing&&p.remoteMode()==2,"Double trigger failed to enter resize");
    const auto center=p.position();hands[1]=aim(p.worldPoint({2,0,0}));update(false,true,2.3);
    check(p.scale()>1.9F&&glm::distance(center,p.position())<1e-5F,"Resize moved center or did not enlarge");
    update(false,false,2.4);
    // Border ownership cannot leak through a nearer panel interior.
    p.openDocked({0,0,-3},glm::quat(1,0,0,0));p.setScale(1);
    front.openDocked({0,0,-1},glm::quat(1,0,0,0));front.setScale(1);
    targets.push_back({&front,b,b});hands[1]=aim({.99F,0,-3});
    update(true,true,3);check(!control.active,"Occluded border acquired through front content");
    targets.pop_back();hands[1]=aim({0,0,-3});update(true,true,4);check(!control.active,"Panel interior acquired a border gesture");
    hands[1]=aim({.99F,0,-3});update(true,true,5);hands[1].valid=false;update(false,true,5.1);
    check(!control.active&&p.remoteMode()==0,"Tracking loss retained grab");
    hands[1]=aim({.99F,0,-3});update(true,true,6);targets.clear();update(false,true,6.1);
    check(!control.active,"Closing panel retained grab");
    p.setScale(4);p.openDocked({0,0,-12},glm::quat(1,0,0,0));targets={{&p,b,b}};hands[1]=aim({3.96F,0,-12});
    update(true,true,7);check(control.active==&p,"Giant distant panel not reachable");control.cancel();
    // External Close is above the actual frame, excluded from desktop UVs.
    DesktopPanel desktop;desktop.show({0,0,0},glm::quat(1,0,0,0));
    const auto close=desktop.closeBounds();
    check(close.minimum.y>desktop.bounds().maximum.y,"Close overlaps outer frame");
    auto h=aim(desktop.placement.worldPoint({(close.minimum.x+close.maximum.x)*.5F,(close.minimum.y+close.maximum.y)*.5F,0}));
    check(desktop.hit(h).has_value()&&!desktop.uv(h),"External Close is clipped or maps to desktop");
    targets={{&desktop.placement,desktop.bounds(),desktop.chromeBounds()}};hands[1]=h;
    update(true,true,8);check(!control.active,"External Close was swallowed by border margin");
    std::cout<<"Remote border movement, radius, resize, occlusion, cancellation and external Close passed\n";
    return 0;
} catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
