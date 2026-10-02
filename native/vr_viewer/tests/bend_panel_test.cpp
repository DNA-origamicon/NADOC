#include "bend_panel.hpp"
#include <cassert>
#include <iostream>
int main() {
    using namespace nadoc_vr;
    BendArc arc;arc.a={0,0,0};arc.b={0,0,1};arc.length=1;
    arc.move(1,{.4F,0,.5F});
    assert(glm::distance(arc.a,glm::vec3(0))<1e-6F);
    assert(glm::distance(arc.point(1),arc.b)<1e-5F);
    float length=0;for(int i=0;i<1000;++i)length+=glm::distance(arc.point(i/1000.F),arc.point((i+1)/1000.F));
    assert(std::abs(length-1)<1e-4F);
    const auto fixed=arc.b;arc.move(0,{-.1F,.1F,-.2F});
    assert(arc.b==fixed);assert(glm::distance(arc.point(1),fixed)<1e-5F);
    arc.move(0,{-10,0,0});assert(glm::distance(arc.a,arc.b)<=1.00001F);
    assert(glm::distance(arc.endTangent(1),arc.tangent)<1e-6F);
    for(size_t fixedEnd=0;fixedEnd<2;++fixedEnd) {
        for(float degrees:{0.F,45.F,90.F,180.F,270.F,359.F}) {
            arc.fixedEnd=fixedEnd;arc.tangent=glm::normalize(glm::vec3(.2F,.3F,1));
            arc.direction=arc.referenceDirection();arc.angle=glm::radians(degrees);arc.updateEndpoint();
            const auto anchor=arc.point(float(fixedEnd));
            assert(glm::distance(arc.endTangent(float(fixedEnd)),arc.tangent)<1e-6F);
            const float t=fixedEnd==0?1:0;
            const auto derivative=glm::normalize(arc.point(t+.0001F)-arc.point(t-.0001F));
            assert(glm::distance(derivative,arc.endTangent(t))<.002F);
            arc.move(1-fixedEnd,arc.point(t)+glm::vec3(.1F,-.2F,.05F));
            assert(glm::distance(arc.point(float(fixedEnd)),anchor)<1e-6F);
            assert(glm::distance(arc.endTangent(float(fixedEnd)),arc.tangent)<1e-6F);
        }
    }
    ToolConfigurationDraft config;
    (void)config.bind(ToolMode::bend,"cluster:1","cluster",{"owner:1"});
    (void)config.setPlaneBp("a",5);(void)config.setPlaneBp("b",105);
    (void)config.adjustSecondary(1);assert(config.bendDirectionDegrees()==1);
    (void)config.adjustPrimary(1);assert(config.bendAngleDegrees()==1);
    std::array<SidebarMenu,2> menus{SidebarMenu(0),SidebarMenu(1)};
    BendPanel panel;panel.enter(menus);panel.refresh(menus,config,"READY");
    std::set<std::string> found;
    do {
        const auto controls=menus[1].controls();
        for(const auto& c:controls)found.insert(c.id);
        for(const auto* id:{"bend:back","bend:confirm","bend:cancel"})
            assert(std::any_of(controls.begin(),controls.end(),[&](const auto& c){return c.id==id;}));
        if(!menus[1].canScroll(1))break;
        menus[1].scroll(1);
    }while(true);
    for(const auto* name:{"plane1","plane2","angle","direction","radius","undo","direction-less","direction-more","radius-less","radius-more"})assert(found.contains(std::string("bend:")+name));
    assert(!menus[1].canScroll(1));
    menus[1].open=false;panel.refresh(menus,config,"READY");assert(menus[1].open);
    menus[1].draw([](auto,auto,auto){},[](auto,auto){});
    std::cerr<<menus[1].audit.summary()<<std::endl;
    assert(menus[1].audit.valid());
    const auto buttons=menus[1].controls();
    for(size_t i=0;i<buttons.size();++i)for(size_t j=i+1;j<buttons.size();++j) {
        const auto a=buttons[i].bounds,b=buttons[j].bounds;
        assert(a.maximum.x<=b.minimum.x || b.maximum.x<=a.minimum.x || a.maximum.y<=b.minimum.y || b.maximum.y<=a.minimum.y);
    }
    menus[1].offsets[menus[1].selected]=0;
    auto find=[&](const std::string& id){return *std::find_if(buttons.begin(),buttons.end(),[&](const auto& c){return c.id==id;});};
    assert(!find("bend:plane1").enabled && find("bend:plane1").action.empty());
    assert(!find("bend:plane2").enabled && find("bend:plane2").action.empty());
    assert(find("bend:angle").bounds.minimum.y==find("bend:radius").bounds.minimum.y);
    for(const auto* field:{"angle","direction","radius"}) {
        assert(find(std::string("bend:")+field+"-wheel").bounds.maximum.x<find(std::string("bend:")+field).bounds.minimum.x);
    }
    menus[1].focus.id="bend:direction-less";menus[1].navigate({1,0});
    assert(menus[1].focus.id=="bend:direction-more");
    assert(!found.contains("tab:tools"));panel.exit(menus);assert(!menus[1].customTab);
    const auto feedback=parseToolExecutionFeedback("NADOCVR_TOOL_EXECUTION 1 1 2 twist confirm cluster cluster:1 succeeded committed feature:twist\n",0,2);
    assert(feedback && feedback->mode=="twist");
    panel.twist=true;panel.enter(menus);
    (void)config.bind(ToolMode::twist,"cluster:1","cluster",{"owner:1"});
    (void)config.setPlaneBp("a",5);(void)config.setPlaneBp("b",105);
    assert(config.setTwist(-90));assert(config.toggleTwistUnits());
    assert(std::abs(config.twistTotalDegrees()+90)<1e-8);
    assert(config.toggleTwistUnits());assert(std::abs(config.twistAmount()+90)<1e-8);
    assert(!config.setTwist(std::numeric_limits<double>::quiet_NaN()));
    panel.refresh(menus,config,"READY");assert(menus[1].tab().key=="twist");
    const auto twist=menus[1].controls();
    for(const auto* id:{"back","confirm","cancel","plane1","plane2","amount","units","reverse","zero","less","more","undo"})
        assert(std::any_of(twist.begin(),twist.end(),[&](const auto& c){return c.id==std::string("twist:")+id;}));
    assert(!menus[1].canScroll(1));
    menus[1].focus.id="twist:less";menus[1].navigate({1,0});assert(menus[1].focus.id=="twist:more");
    for(size_t i=0;i<twist.size();++i)for(size_t j=i+1;j<twist.size();++j) {
        const auto a=twist[i].bounds,b=twist[j].bounds;
        assert(a.maximum.x<=b.minimum.x || b.maximum.x<=a.minimum.x || a.maximum.y<=b.minimum.y || b.maximum.y<=a.minimum.y);
    }
    // A cached menu must track every displayed input and recover after another
    // panel replaces it, without disturbing the focused control.
    auto checkRefresh=[&](const std::string& status) {
        const auto focus=menus[1].focus.id;
        panel.refresh(menus,config,status);
        assert(menus[1].focus.id==focus);
        BendPanel fresh;fresh.twist=panel.twist;fresh.elements=panel.elements;
        std::array<SidebarMenu,2> expected{SidebarMenu(0),SidebarMenu(1)};
        fresh.enter(expected);fresh.refresh(expected,config,status);
        const auto& a=menus[1].tab();const auto& b=expected[1].tab();
        assert(a.key==b.key && a.rows.size()==b.rows.size());
        for(size_t i=0;i<a.rows.size();++i) {
            assert(a.rows[i].id==b.rows[i].id && a.rows[i].label==b.rows[i].label);
            assert(a.rows[i].section==b.rows[i].section && a.rows[i].action==b.rows[i].action);
        }
    };
    checkRefresh("READY");checkRefresh("HOLDING");
    (void)config.setTwist(120);checkRefresh("HOLDING");
    (void)config.toggleTwistUnits();checkRefresh("HOLDING");
    (void)config.setPlaneBp("b",120);checkRefresh("HOLDING");
    panel.elements=true;checkRefresh("HOLDING");
    panel.twist=false;checkRefresh("HOLDING");
    (void)config.bind(ToolMode::bend,"cluster:1","cluster",{"owner:1"});
    (void)config.setPlaneBp("a",10);(void)config.setPlaneBp("b",110);
    (void)config.adjustPrimary(45);checkRefresh("READY");
    (void)config.adjustSecondary(90);checkRefresh("READY");
    menus[1].customTab.reset();checkRefresh("READY");
    panel.exit(menus);panel.enter(menus);checkRefresh("READY");
}
