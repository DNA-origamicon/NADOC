#include "bend_panel.hpp"
#include <cassert>
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
    const auto buttons=menus[1].controls();
    for(size_t i=0;i<buttons.size();++i)for(size_t j=i+1;j<buttons.size();++j) {
        const auto a=buttons[i].bounds,b=buttons[j].bounds;
        assert(a.maximum.x<=b.minimum.x || b.maximum.x<=a.minimum.x || a.maximum.y<=b.minimum.y || b.maximum.y<=a.minimum.y);
    }
    menus[1].offsets[menus[1].selected]=0;
    menus[1].focus.id="bend:plane1";menus[1].navigate({1,0});
    assert(menus[1].focus.id=="bend:plane2");
    assert(!found.contains("tab:tools"));panel.exit(menus);assert(!menus[1].customTab);
}
