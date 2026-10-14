#include "join_preview.hpp"
#include "move_panel.hpp"
#include <cassert>
#include <chrono>
#include <iostream>
int main() {
    using namespace nadoc_vr;
    const auto record="NADOC_JOIN_1 1 2 3 valid 1 1 1 2 Ready\n0 0 0 1 0 0\n0 0 0 0 1 0 0\n1 1 0 0 -1 0 0\n";
    assert(joinMessage("Checking%E2%80%A6")=="Checking...");
    assert(!joinMessage("bad%0Aline") && !joinMessage("bad%zz"));
    auto feedback=parseJoinFeedback(record);assert(feedback && feedback->sites && feedback->sites->fixed.size()==1);
    const auto repeat=parseJoinFeedback(record,feedback);assert(repeat->sites==feedback->sites);
    assert(!parseJoinFeedback(std::string(record)+"trailing",feedback));
    assert(!parseJoinFeedback("NADOC_JOIN_1 1 2 3 valid 1 1 129 0 Ready\n"));
    assert(!parseJoinFeedback("NADOC_JOIN_1 1 2 3 valid 1 1 0 8193 Ready\n"));
    assert(!parseJoinFeedback("NADOC_JOIN_1 1 2 3 valid 1 1 0 1 Ready\n1 0 0 0 0 0 0"));
    JoinPreview preview;
    assert(!preview.accept(feedback,1,3) && !preview.accept(feedback,2,2));
    assert(preview.accept(feedback,2,3) && preview.ready(2,3));
    assert(!preview.ready(2,4) && !preview.ready(3,3));
    preview.update(glm::mat4(1));assert(preview.hintCount==1);
    assert(preview.hints[0].second==glm::vec3(1,0,0));
    preview.update(glm::translate(glm::mat4(1),glm::vec3(5,0,0)));assert(preview.hintCount==0);
    preview.update(glm::translate(glm::mat4(1),glm::vec3(5,0,0)),7.F);assert(preview.hintCount==1);
    preview.update(glm::translate(glm::mat4(1),glm::vec3(5,0,0)),3.F);assert(preview.hintCount==0);
    preview.update(glm::rotate(glm::mat4(1),glm::pi<float>(),glm::vec3(0,1,0)));assert(preview.hintCount==0);
    preview.clear();assert(!preview.ready(2,3) && !preview.sites && !preview.accept(feedback,2,3));
    // Crowded cell stress remains bounded independently of scene and site count.
    auto crowded=std::make_shared<JoinSiteIndex>();
    for(size_t i=0;i<8192;++i)crowded->add({i<4096,{i<4096?1.F:0.F,float(i%8)*.01F,0},{i<4096?-1.F:1.F,0,0}});
    preview.sites=crowded;double maximum=0;
    for(int frame=0;frame<2000;++frame) {
        const auto begin=std::chrono::steady_clock::now();
        preview.update(glm::translate(glm::mat4(1),glm::vec3(float(frame%70)*.0001F,0,0)));
        maximum=std::max(maximum,std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-begin).count());
        assert(preview.comparisons<=JoinPreview::maximumComparisons && preview.hintCount<=JoinPreview::maximumHints);
    }
    std::cout<<"join_proximity_8192_sites_frames=2000 maximum_cpu_ms="<<maximum<<" pair_budget="<<JoinPreview::maximumComparisons<<'\n';
    MovePanel panel;panel.joining=true;panel.positionNm={.49F,.51F,-.51F};panel.rotationDegrees={7.F,8.F,-8.F};
    panel.adjust(0,1);panel.adjust(1,-1);panel.adjust(2,1);panel.adjust(3,1);panel.adjust(4,-1);panel.adjust(5,1);
    assert(panel.positionNm==glm::vec3(1,0,0) && panel.rotationDegrees==glm::vec3(15,0,0));
    std::array<SidebarMenu,2> menus{SidebarMenu(0),SidebarMenu(1)};
    panel.enter(menus);panel.refresh(menus,"cluster","READY");
    assert(menus[1].tab().key=="join" && menus[1].tab().label=="Join");
    const auto controls=menus[1].controls();
    for(const auto id:{"join:0-wheel","join:5-wheel","join:apply","join:cancel"})assert(std::any_of(controls.begin(),controls.end(),[&](const auto& c){return c.id==id;}));
    const auto apply=std::find_if(controls.begin(),controls.end(),[](const auto& c){return c.id=="join:apply";});
    const auto cancel=std::find_if(controls.begin(),controls.end(),[](const auto& c){return c.id=="join:cancel";});
    assert(cancel->bounds.minimum.y==apply->bounds.minimum.y && cancel->bounds.maximum.x<apply->bounds.minimum.x);
    menus[1].draw([](auto,auto,auto){},[](auto,auto){});
    std::cerr<<menus[1].audit.summary()<<'\n';assert(menus[1].audit.valid());
    panel.reset();assert(panel.transform()==glm::mat4(1));
    assert(ToolShell::selectionCapability(ToolMode::join,"cluster")==ToolCapability::direct_preview);
    assert(ToolShell::selectionCapability(ToolMode::join,"domain")==ToolCapability::unsupported);
}
