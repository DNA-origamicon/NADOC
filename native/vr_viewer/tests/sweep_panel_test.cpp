#include "sweep_panel.hpp"
#include <cassert>
#include <iostream>
#include <set>

using namespace nadoc_vr;
int main() {
    assert(sweepPositionNumber(1.239F)=="1.23");
    assert(sweepPositionNumber(-1.239F)=="-1.23");
    assert(sweepPositionNumber(15.12F)=="15.12");
    assert(sweepPositionNumber(-.001F)=="0.00");
    std::array<SidebarMenu,2> menus{SidebarMenu(0),SidebarMenu(1)};
    auto& menu=menus[1];menu.offsets[menu.selected]=8;
    SweepPanel panel;SweepDraft draft;panel.enter(menus);
    auto refresh=[&]{panel.refresh(menus,draft,6,false,"BOTH",true,"READY");};
    auto control=[&](const std::string& id) {
        auto controls=menu.controls(false);
        const auto found=std::find_if(controls.begin(),controls.end(),[&](const auto& c){return c.id==id;});
        assert(found!=controls.end());return *found;
    };
    auto audit=[&] {
        menu.draw([](glm::vec3,glm::vec3,glm::vec3){},[](MenuPanelBounds,glm::vec3){});
        if(!menu.audit.valid())std::cerr<<menu.audit.summary()<<'\n';
        assert(menu.audit.valid());
    };
    refresh();assert(menu.toolFooter());
    assert(control("sweep:confirm").label=="NEXT");assert(menu.raisedAction(control("sweep:confirm")));
    std::set<std::string> found;
    do {
        audit();
        for(const auto& c:menu.controls(false))found.insert(c.id);
        control("sweep:back");control("sweep:confirm");
        if(!menu.canScroll(1))break;
        menu.scroll(1);
    }while(true);
    for(const auto id:{"plane","lattice","strands","ligate","paint","undo","recenter","cancel"})assert(found.contains(std::string("sweep:")+id));
    draft.next();refresh();assert(menu.offset()==0 && menu.total()==2 && menu.pageRows()==2);
    assert(control("sweep:confirm").label=="CONFIRM");
    assert(control("sweep:free-draw").label=="FREE DRAW");
    assert(control("sweep:bp-info").label=="NEW BP: CALCULATING");
    assert(!control("sweep:bp-info").enabled);
    assert(control("sweep:axis:0:0:1").enabled && control("sweep:axis:1:0:1").enabled);
    assert(control("sweep:axis:1:2:value").label=="Z 10.00");audit();
    for(int i=0;i<9;++i)draft.addPoint();
    refresh();
    assert(menu.offset()==draft.selected-1);control("sweep:point:"+std::to_string(draft.selected));audit();
    menu.scroll(-1);const auto manualOffset=menu.offset();refresh();assert(menu.offset()==manualOffset);
    draft.select(0);refresh();assert(menu.offset()==0);audit();
    draft.movePoint(1,{-10000,9999,10000});refresh();audit();
    assert(control("sweep:axis:1:0:value").label=="X -10000.00");
    assert(std::any_of(menu.audit.texts().begin(),menu.audit.texts().end(),[](const auto& t){return t.text=="-10000.00";}));
    draft.movePoint(1,{-16.818F,33.167F,-.379F});refresh();audit();
    assert(std::any_of(menu.audit.texts().begin(),menu.audit.texts().end(),[](const auto& t){return t.text=="-16.81";}));
    // Animated scrolling shares a clipped drawing and hit viewport; partial
    // rows must not overlap the pinned Free Draw or smoothing controls.
    double clock=100;menu.animationClock=[&]{return clock;};
    menu.scrollRow(1);clock+=.10;audit();
    clock+=.20;menu.offsets[menu.selected]=0;menu.rowScroll={};
    found.clear();
    do {
        audit();
        for(const auto& c:menu.controls(false))found.insert(c.id);
        control("sweep:free-draw");control("sweep:back");control("sweep:confirm");
        if(!menu.canScroll(1))break;
        menu.scroll(1);
    }while(true);
    for(size_t i=0;i<draft.pointsNm.size();++i)for(int axis=0;axis<3;++axis)
        for(const auto side:{"-1","1","value"})assert(found.contains("sweep:axis:"+std::to_string(i)+":"+std::to_string(axis)+":"+side));
    // Raised button picking uses the shared extrude surface depth.
    menu.placement.openDocked({0,0,0},glm::quat(1,0,0,0));
    const auto confirm=control("sweep:confirm");const auto center=(confirm.bounds.minimum+confirm.bounds.maximum)*.5F;
    const glm::vec3 target(center.x,confirm.bounds.maximum.y-.005F,.035F),origin=target+glm::vec3(0,-.4F,.4F);
    HandPose ray{true,false,menu.placement.worldPoint(origin),menu.placement.orientation()*glm::quatLookAt(glm::normalize(target-origin),glm::vec3(0,1,0))};
    assert(menu.hit(ray)->id=="sweep:confirm");
    assert(std::abs(menu.raySurfacePoint(ray)->z-.035F)<1e-5F);
    panel.exit(menus);assert(!menu.customTab && menu.offset()==8);
    std::cout<<"Sweep wizard, coordinate arrows, scroll, footer and raised picking passed\n";
}
