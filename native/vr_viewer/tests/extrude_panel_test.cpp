#include "lattice_grip.hpp"
#include "extrude_panel.hpp"
#include <cassert>
int main() {
    using namespace nadoc_vr;
    std::array<SidebarMenu,2> menus{SidebarMenu(0),SidebarMenu(1)};
    menus[1].offsets[menus[1].selected]=8;
    ExtrudePanel panel;panel.enter(menus);
    panel.refresh(menus,42,1,"EXTRUDE FROM XY","BOTH",true,6,false,false,"READY");
    std::set<std::string> found;
    do {
        auto controls=menus[1].controls();
        for(const auto& id:{"extrude:back","extrude:confirm","extrude:cancel"})
            assert(std::any_of(controls.begin(),controls.end(),[&](const auto& c){return c.id==id;}));
        for(const auto& c:controls)found.insert(c.id);
        if(!menus[1].canScroll(1))break;
        menus[1].scroll(1);
    }while(true);
    for(const auto& name:{"less","more","direction","plane","lattice","strands","ligate","paint","freeform","undo","cancel"})
        assert(found.contains(std::string("extrude:")+name));
    menus[1].offsets[menus[1].selected]=0;
    auto controls=menus[1].controls();
    auto get=[&](const std::string& id){return *std::find_if(controls.begin(),controls.end(),[&](const auto& c){return c.id==id;});};
    const auto minus=get("extrude:less-period"),plus=get("extrude:more-period");
    assert(minus.bounds.maximum.x<plus.bounds.minimum.x);
    assert(minus.bounds.minimum.y==plus.bounds.minimum.y);
    menus[1].focus.id=minus.id;menus[1].navigate({1,0});assert(menus[1].focus.id==plus.id);
    for(bool square:{false,true}) {
        panel.refresh(menus,48,1,"EXTRUDE FROM XY","BOTH",true,6,square,false,"READY");
        controls=menus[1].controls();
        const std::string fine=square?"8":"7",coarse=square?"24":"21";
        assert(get("extrude:less").label=="-"+fine+" BP");
        assert(get("extrude:more").label=="+"+fine+" BP");
        assert(get("extrude:less-period").label=="-"+coarse+" BP");
        assert(get("extrude:more-period").label=="+"+coarse+" BP");
    }
    MenuPlacement placement;placement.openDocked({0,0,0},glm::quat(1,0,0,0));
    LatticeGrip grip;
    std::array<HandPose,2> hands{};
    for(auto& h:hands){h.valid=true;h.pressed=true;}
    auto update=[&](std::array<bool,2> clicked={false,false}) {
        return grip.update(placement,hands,clicked,{-.272F,-.205F},{.272F,.210F},{-.29F,-.31F},{.29F,.31F},true);
    };
    for(float depth:{-.08F,.08F}) {
        grip.cancel();grip.zoom=1;
        hands[0].position={-.06F,0,depth};hands[1].position={.06F,0,depth};
        update({true,false});assert(grip.held[0] && !grip.scaling);
        update({false,true});assert(grip.scaling);
        hands[0].position.x=-.09F;hands[1].position.x=.09F;
        update();assert(std::abs(grip.zoom-1.5F)<.001F);
        hands[1].position.z+=.3F;update();assert(std::abs(grip.zoom-1.5F)<.001F);
        hands[1].valid=false;update();assert(!grip.scaling);hands[1].valid=true;
    }
    grip.cancel();hands[0].position={-.06F,0,.12F};hands[1].position={.06F,0,.12F};
    update({true,true});assert(!grip.held[0] && !grip.held[1]);
    hands[0].position=placement.worldPoint({-.29F,0,0});
    hands[1].position=placement.worldPoint({.29F,0,0});
    update({true,true});assert(!grip.held[0] && !grip.held[1]);
    assert(placement.beginBorderResize(hands,{-.29F,-.31F},{.29F,.31F}));
    panel.exit(menus);assert(!menus[1].customTab);assert(menus[1].offset()==8);
}
