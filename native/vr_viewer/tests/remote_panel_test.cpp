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
    const auto anchor=glm::inverse(hands[1].orientation)*(p.worldPoint({.99F,0,0})-hands[1].position);
    hands[1].orientation=glm::angleAxis(.25F,glm::vec3(0,1,0))*hands[1].orientation;
    update(false,true,1.2);
    check(glm::distance(initial,p.position())>.5F,"Ray sweep did not move distant panel");
    hands[1].position+=glm::vec3(.2F,.1F,-.4F);update(false,true,1.25);
    check(glm::distance(glm::inverse(hands[1].orientation)*(p.worldPoint({.99F,0,0})-hands[1].position),anchor)<1e-4F,"Grab did not preserve controller-local ray anchor");
    const auto beforeHead=p.position();control.update(targets,hands,{false,false},{false,true},{1,2,3},1.26);
    check(glm::distance(beforeHead,p.position())<1e-5F,"Head movement moved grabbed menu");
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
    // The other controller can join a distant grab, then either hand can release.
    for(size_t first=0;first<2;++first) {
        control.cancel();p.openDocked({0,0,-3},glm::quat(1,0,0,0));p.setScale(1);
        hands[0]=aim({-.99F,0,-3});hands[1]=aim({.99F,0,-3});
        std::array<bool,2> held{},click{};held[first]=click[first]=true;
        control.update(targets,hands,click,held,{},10);
        click[first]=false;held[1-first]=click[1-first]=true;
        auto blocked=control.update(targets,hands,click,held,{},10.1);
        check(blocked[0]&&blocked[1]&&control.resizing,"Second controller did not acquire remote resize");
        hands[0].position.x-=.3F;hands[1].position.x+=.3F;click.fill(false);
        control.update(targets,hands,click,held,{},10.2);
        check(p.scale()>1.25F&&glm::distance(p.position(),glm::vec3(0,0,-3))<1e-4F,"Two-ray resize failed");
        held[first]=false;const auto before=p.position();
        control.update(targets,hands,click,held,{},10.3);
        check(control.active==&p&&!control.resizing&&glm::distance(before,p.position())<1e-4F,"Resize release jumped or lost remaining grab");
        hands[1-first].position.z-=.2F;control.update(targets,hands,click,held,{},10.4);
        check(std::abs(p.position().z-before.z+.2F)<1e-4F,"Remaining hand did not move panel");
        held.fill(false);control.update(targets,hands,click,held,{},10.5);
        check(!control.active,"Two-hand release retained ownership");
    }
    control.cancel();p.openDocked({0,0,-3},glm::quat(1,0,0,0));p.setScale(1);
    hands[0]=aim({-.99F,0,-3});hands[1]=aim({.99F,0,-3});
    control.update(targets,hands,{true,true},{true,true},{},11);
    check(control.resizing,"Simultaneous triggers did not resize");
    targets.clear();control.update(targets,hands,{false,false},{true,true},{},11.1);
    check(!control.active&&p.remoteMode()==0,"Closing two-hand panel retained gesture");
    targets={{&p,b,b}};update(true,true,11.2);
    check(control.active==&p&&!control.resizing,"Closed two-hand gesture contaminated next grab");
    control.cancel();
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
    std::cout<<"Remote border movement, fixed ray anchor, two-hand resize, occlusion, cancellation and external Close passed\n";
    return 0;
} catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
