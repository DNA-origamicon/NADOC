#include "sidebar_menu.hpp"
#include <iostream>
#include <set>
#include <stdexcept>
int main() {
    int failures=0;size_t count=0;
    auto require=[](bool valid,const char* reason){if(!valid)throw std::runtime_error(reason);};
    // Removing a named accent must not leave a zero-filled entry whose empty
    // name matches every control and bypasses all fallback colors.
    require(nadoc_vr::ui_style::buttonAccent("close")==nadoc_vr::ui_style::danger,"Close lost its danger accent");
    require(nadoc_vr::ui_style::buttonAccent("tab:visualization")==nadoc_vr::ui_style::accent,"Tab lost its blue accent");
    const auto fallback=nadoc_vr::ui_style::buttonAccent("menu-view-cylinders");
    require(std::max({fallback.r,fallback.g,fallback.b})>.5F,"Unmapped button accent became black");
    for(bool assembly:{false,true}) {
        nadoc_vr::SidebarMenu menu(1,assembly);menu.open=true;
        const auto controls=menu.controls();
        const bool shown=std::any_of(controls.begin(),controls.end(),[](const auto& c){return c.id=="tab:assembly";});
        require(shown==assembly,"Assembly tab must match the document context");
        require(menu.tab().key=="properties","Default Properties tab changed with Assembly visibility");
    }
    const auto vrTab=std::find_if(nadoc_vr::kSidebarTabs.begin(),nadoc_vr::kSidebarTabs.end(),[](const auto& tab){return tab.key=="vr";});
    require(vrTab!=nadoc_vr::kSidebarTabs.end(),"VR tab missing");
    nadoc_vr::SidebarMenu part(1);
    require(std::none_of(part.tabs.begin(),part.tabs.end(),[](auto i){return nadoc_vr::kSidebarTabs[i].key=="assembly";}),"Part session exposed Assembly navigation");
    nadoc_vr::MenuFocus focus;
    focus.begin("a","resting");
    require(!focus.pointer("resting",10,false),"Resting pointer stole focus");
    require(!focus.pointer("resting",20,false),"Time alone stole focus");
    require(!focus.pointer("",21,false),"Empty ray selected pointer mode");
    require(!focus.pointer("target",22,false),"No dwell delay");
    require(!focus.pointer("target",22.2,false),"Short dwell stole focus");
    require(!focus.pointer("other",22.3,false),"Changing target retained dwell");
    require(!focus.pointer("other",22.8,true),"Held trigger allowed mode switch");
    require(!focus.pointer("other",23,false),"Held trigger did not reset dwell");
    require(focus.pointer("other",23.5,false)&&!focus.active,"Stable deliberate aim failed");
    focus.begin("a","");focus.step({"a","disabled","c"},1);
    require(focus.id=="disabled","Unavailable targets must be discoverable");
    focus.step({"a","disabled","c"},-1);focus.step({"a","disabled","c"},-1);
    require(focus.id=="a","Focus must stop at top");
    focus.step({"a","disabled","c"},20);require(focus.id=="c","Focus must stop at bottom");
    focus.reset();require(!focus.active&&focus.id.empty(),"Explicit pointer reset failed");

    for(int hand=0;hand<2;++hand) {
        nadoc_vr::SidebarMenu menu(hand,true);menu.open=true;
        for(size_t tab=0;tab<menu.tabs.size();++tab) {
            menu.selected=tab;std::set<std::string> seen;
            do {
                menu.draw([](glm::vec3,glm::vec3,glm::vec3){},[](nadoc_vr::MenuPanelBounds,glm::vec3){});
                const auto controls=menu.controls();
                const auto quick=std::find_if(controls.begin(),controls.end(),[](const auto& c){return c.id=="menu-view-surface";});
                const auto detail=std::find_if(controls.begin(),controls.end(),[](const auto& c){return c.id=="menu-view-surface-detail";});
                if(quick!=controls.end()) {
                    require(detail!=controls.end(),"Surface presets must be on the same page");
                    require(quick->bounds.minimum.y==detail->bounds.minimum.y,"Surface presets must share a row");
                    require(quick->bounds.maximum.x<detail->bounds.minimum.x,"Surface presets must not overlap");
                    require(quick->action=="repr:7" && detail->action=="repr:11","Surface presets must select distinct geometry");
                }

                if(!menu.audit.valid()) {std::cerr<<menu.tab().key<<"/"<<menu.offset()<<": "<<menu.audit.summary()<<'\n';++failures;}
                const auto track=menu.scrollBounds(),thumb=menu.scrollThumb();
                require(nadoc_vr::menuLayoutContains(track,thumb),"Scrollbar thumb outside track");
                for(const auto& c:menu.controls()) {
                    require(!c.id.starts_with("scroll:"),"Old scroll buttons remain");
                    if(c.vertical||c.id=="scrollbar"||c.id=="close"||c.id=="dock")continue;
                    if(!seen.insert(c.id).second) throw std::runtime_error("Duplicate row "+c.id);
                    if(!c.enabled) {
                        auto old=menu.offset();
                        if(!menu.activate(c).empty()||menu.selected!=tab||menu.offset()!=old||!menu.open) throw std::runtime_error("Disabled control changed state");
                    }
                }
                if(!menu.canScroll(1))break;
                menu.scroll(1);
            }while(true);
            if(seen.size()!=menu.tab().rows.size())throw std::runtime_error("Unreachable rows");
            count+=seen.size();
            auto last=menu.offset();menu.scroll(1);if(menu.offset()!=last)throw std::runtime_error("Scroll overflow");
            while(menu.canScroll(-1))menu.scroll(-1);
            menu.scroll(-1);if(menu.offset()!=0)throw std::runtime_error("Scroll underflow");
        }
    }
    // Collapse uses desktop ancestry, not matching labels or neighboring rows.
    for(int hand=0;hand<2;++hand) {
        nadoc_vr::SidebarMenu menu(hand);menu.open=true;
        menu.available=[](const auto&){return false;};
        for(size_t tab=0;tab<menu.tabs.size();++tab) {
            menu.selected=tab;
            const auto full=menu.total();
            for(size_t index=0;index<menu.tab().rows.size();++index) {
                const auto& header=menu.tab().rows[index];
                if(!header.action.starts_with("section:") || (header.id=="section:properties:dimensions-heading" || header.id=="section:visualization:template:view-volumes")) continue;
                const auto rows=menu.visibleRows();
                const auto logical=std::find_if(rows.begin(),rows.end(),[&](const auto* row){return row->id==header.id;})-rows.begin();
                menu.offsets[tab]=size_t(logical)/nadoc_vr::kSidebarPageRows*nadoc_vr::kSidebarPageRows;
                auto controls=menu.controls();
                auto title=std::find_if(controls.begin(),controls.end(),[&](const auto& c){return c.id==header.id;});
                require(title!=controls.end() && title->enabled,"Card title unavailable with disabled contents");
                menu.focus.begin(header.id,"");
                require(menu.activate(*title).empty(),"Card dispatched an external action");
                size_t hidden=0;
                for(const auto& row:menu.tab().rows) if(row.id!="menu-view-surface-detail" && std::find(row.parents.begin(),row.parents.end(),header.id)!=row.parents.end()) ++hidden;
                require(menu.total()==full-hidden,"Card hid unrelated controls or retained descendants");
                require(menu.focus.id==header.id,"Collapse lost title focus");
                controls=menu.controls();
                require(std::any_of(controls.begin(),controls.end(),[&](const auto& c){return c.id==header.id;}),"Collapsed title scrolled away");
                menu.draw([](glm::vec3,glm::vec3,glm::vec3){},[](nadoc_vr::MenuPanelBounds,glm::vec3){});
                require(menu.audit.valid(),"Collapsed card layout invalid");
                menu.toggleSection(header.id);
                require(menu.total()==full,"Expand did not restore children");
            }
            for(const auto& child:menu.tab().rows) if(child.action.starts_with("section:")&&!child.parents.empty()) {
                const auto parent=child.parents.front();
                menu.toggleSection(child.id);
                const auto count=menu.total();
                menu.toggleSection(parent);
                menu.open=false;menu.selected=(tab+1)%menu.tabs.size();menu.selected=tab;menu.open=true;
                require(menu.collapsed.contains(parent)&&menu.collapsed.contains(child.id),"Tab/toggle lost section state");
                menu.toggleSection(parent);
                require(menu.total()==count&&menu.collapsed.contains(child.id),"Parent expansion reset child state");
                menu.toggleSection(child.id);
                break;
            }
        }
    }
    int curvedEdges=0;
    const nadoc_vr::MenuPanelBounds box{{0,0},{1,1}};
    nadoc_vr::ui_style::rounded(box,{0,0,0},{1,1,1},
        [&](glm::vec3 a,glm::vec3 b,glm::vec3) {if(a.x!=b.x&&a.y!=b.y)++curvedEdges;},
        [&](nadoc_vr::MenuPanelBounds fill,glm::vec3) {
            require(nadoc_vr::menuLayoutContains(box,fill),"Rounded fill outside hit box");
            require(fill.minimum.x>0 || fill.minimum.y>0,"Square corner still filled");
        });
    require(curvedEdges>=24,"Rounded perimeter missing");
    nadoc_vr::SidebarMenu scrolling(0);scrolling.selected=1;
    scrolling.focus.begin("scrollbar","");
    scrolling.navigate({0,-1});
    require(scrolling.offset()==1 && scrolling.focus.id=="scrollbar","Pad down must scroll and retain focus");
    scrolling.navigate({0,1});require(scrolling.offset()==0,"Pad up must scroll back");
    scrolling.navigate({-1,0});require(scrolling.focus.id!="scrollbar","Cannot exit scrollbar to rows");
    scrolling.scrollTo(-100);require(!scrolling.canScroll(1),"Pointer cannot reach bottom");
    scrolling.scrollTo(100);require(scrolling.offset()==0,"Pointer cannot reach top");
    scrolling.focus.begin("scrollbar","");scrolling.navigate({1,0});
    require(!scrolling.focus.id.starts_with("tab:") && scrolling.focus.id!="scrollbar","Cannot exit scrollbar to content");
    for(int hand=0;hand<2;++hand) {
        nadoc_vr::SidebarMenu menu(hand);
        const auto selected=menu.selected;
        auto items=menu.controls();
        const auto first=items.front().id;
        std::string last;
        for(const auto& c:items) if(c.vertical) last=c.id;
        menu.focus.begin(first,"");
        menu.navigate({0,1});require(menu.focus.id==first,"Tabs wrap above top");
        for(int i=0;i<1000;++i) menu.navigate({0,-1});
        require(menu.focus.id==last,"Tabs escape below bottom");
        require(menu.selected==selected,"Navigation activated a tab without trigger");
        const float inward=hand==0?1.F:-1.F;
        menu.navigate({inward,0});require(menu.focus.id=="scrollbar","Tabs must cross scrollbar");
        menu.navigate({inward,0});
        require(menu.focus.id!="scrollbar"&&!menu.focus.id.starts_with("tab:"),"Scrollbar must enter content");
        for(int i=0;i<1000;++i) menu.navigate({0,-1});
        const auto bottom=menu.focus.id;
        menu.navigate({0,-1});require(menu.focus.id==bottom,"Content wraps below bottom");
        for(int i=0;i<1000;++i) menu.navigate({0,1});
        const auto top=menu.focus.id;
        menu.navigate({0,1});require(menu.focus.id==top,"Content wraps above top");
        menu.navigate({-inward,0});require(menu.focus.id=="scrollbar","Content must cross scrollbar");
        menu.navigate({-inward,0});require(menu.focus.id.starts_with("tab:"),"Scrollbar must enter tabs");
    }
    {
        glm::vec3 a(-2,0,0),b(2,0,0);
        const nadoc_vr::MenuPanelBounds clip{{-1,-1},{1,1}};
        require(nadoc_vr::clipSidebarLine(a,b,clip) && a.x==-1 && b.x==1,"Crossing stroke was not clipped");
        a={-2,2,0};b={2,2,0};
        require(!nadoc_vr::clipSidebarLine(a,b,clip),"Offscreen stroke escaped clipping");
        nadoc_vr::SidebarScroll motion;motion.move(0,1,1);
        motion.move(1,0,1.1);
        require(std::abs(motion.value(0,1.1)-.5F)<.001F,"Reversing scroll jumped");
        require(motion.value(0,2)==0,"Reverse scroll failed to settle");
    }
    // A down click reveals exactly one next row, with continuous 200 ms motion.
    for(int hand=0;hand<2;++hand) {
        nadoc_vr::SidebarMenu menu(hand);
        double time=100;menu.animationClock=[&]{return time;};
        menu.selected=1;
        const auto rows=menu.visibleRows();
        require(rows.size()>8,"Scroll fixture needs overflow");
        menu.focus.begin(rows[7]->id,"");
        menu.navigate({0,-1});
        require(menu.offset()==1 && menu.focus.id==rows[8]->id,"Down did not reveal next item");
        require(menu.rowScroll.value(1,time)==0,"Scroll jumped immediately");
        time+=.001;
        for(const auto& c:menu.controls())require(c.bounds.maximum.y>c.bounds.minimum.y,"Invisible animated row exported an inverted hit box");
        time+=.099;
        require(std::abs(menu.rowScroll.value(1,time)-.5F)<.001F,"Scroll midpoint is not smooth");
        const auto items=menu.controls();
        for(const auto& c:items) if(c.viewport) {
            require(nadoc_vr::menuLayoutContains(*c.viewport,c.bounds),"Animated hit target escapes viewport");
        }
        menu.draw([](glm::vec3,glm::vec3,glm::vec3){},[](nadoc_vr::MenuPanelBounds,glm::vec3){});
        require(menu.audit.valid(),"Animated layout audit failed");
        time+=.11;
        require(menu.rowScroll.value(1,time)==1,"Scroll did not settle");
        menu.navigate({0,1}); // previous visible row, no scrolling
        require(menu.offset()==1 && menu.focus.id==rows[7]->id,"Up skipped a row");
        for(int i=0;i<7;++i)menu.navigate({0,1});
        require(menu.offset()==0 && menu.focus.id==rows[0]->id,"Up did not reveal previous item");
        time+=1;
        for(const auto& c:menu.controls()) {
            auto r=std::find_if(rows.begin(),rows.end(),[&](const auto* row){return row->id==c.id;});
            if(r!=rows.end()) {
                const float base=hand==0?.058F-.247F:-.058F-.327F;
                require(std::abs(c.bounds.minimum.x-base-.022F*float((*r)->parents.size()))<.00001F,"Child indent does not match ancestry");
            }
        }
    }
    // Selection-dependent actions must pass through the same disabled gate.
    nadoc_vr::SidebarMenu tools(1);
    tools.open=true;
    tools.selected=tools.tabs.size()-1;
    tools.available=[](const std::string&){return false;};
    for(const auto& control:tools.controls()) {
        if(!control.action.starts_with("tool:")) continue;
        if(control.enabled || !tools.activate(control).empty())
            throw std::runtime_error("Unavailable tool dispatched");
    }
    tools.available=[](const std::string&){return true;};
    for(const auto& control:tools.controls()) {
        if(control.action=="tool:inspect" &&
           (!control.enabled || tools.activate(control)!="tool:inspect"))
            throw std::runtime_error("Available tool not dispatched");
    }
    nadoc_vr::SidebarMenu left(0),right(1);
    left.open=true;right.open=true;right.selected=2;left.open=false;
    if(!right.open||right.selected!=2)throw std::runtime_error("Coupled sidebars");
    std::cout<<count<<" controls checked; "<<failures<<" layout failures\n";
    return failures?1:0;
}
