#include "bend_panel.hpp"
#include "extrude_panel.hpp"
#include "move_panel.hpp"
#include "dimension_panel.hpp"
#include "view_volume_panel.hpp"
#include "simulation_panel.hpp"
#include <iostream>
#include <map>
#include <stdexcept>
using namespace nadoc_vr;
static size_t layouts=0;
static void check(SidebarMenu& menu) {
    menu.draw([](glm::vec3,glm::vec3,glm::vec3){},[](MenuPanelBounds,glm::vec3){});
    if(!menu.audit.valid())throw std::runtime_error(menu.tab().key+": "+menu.audit.summary());
    if(menu.toolFooter()) {
        const float footerTop=menu.footerY()+ui_style::footerHalfHeight+.004F;
        for(const auto& c:menu.controls(false))if(!menu.raisedAction(c) &&
            c.bounds.minimum.y-footerTop+ kMenuLayoutEpsilon<ui_style::contentPadding)
            throw std::runtime_error(menu.tab().key+": footer needs a section gap");
        std::map<float,MenuPanelBounds> rows;
        for(const auto& c:menu.controls(false)) {
            if(SidebarMenu::isScrollbar(c.id))continue;
            const auto [it,inserted]=rows.emplace(c.bounds.minimum.y,c.bounds);
            if(!inserted) {
                it->second.minimum=glm::min(it->second.minimum,c.bounds.minimum);
                it->second.maximum=glm::max(it->second.maximum,c.bounds.maximum);
            }
        }
        for(const auto& [y,b]:rows) {
            const float right=menu.tab().key=="extrude" && y>menu.footerY()?ui_style::toolHalfWidth-.080F:ui_style::toolHalfWidth;
            if(std::abs(b.minimum.x+ui_style::toolHalfWidth)>kMenuLayoutEpsilon || std::abs(b.maximum.x-right)>kMenuLayoutEpsilon)
                throw std::runtime_error(menu.tab().key+": row does not align to content rails");
        }
    }
    ++layouts;
}
static void pages(SidebarMenu& menu) {
    menu.offsets[menu.selected]=0;
    if(menu.canScroll(1)) {
        double now=10;menu.animationClock=[&]{return now;};
        menu.scrollRow(1);now+=.10;check(menu);
        menu.rowScroll={};menu.offsets[menu.selected]=0;
        menu.animationClock=SidebarScroll::now;
    }
    do {check(menu);if(!menu.canScroll(1))break;menu.scroll(1);}while(true);
}
int main() {
    for(int hand:{0,1})for(bool assembly:{false,true}) {
        SidebarMenu menu(hand,assembly);
        for(size_t i=0;i<menu.tabs.size();++i){menu.selected=i;pages(menu);}
    }
    for(bool enabled:{false,true}) {
        std::array<SidebarMenu,2> menus{SidebarMenu(0),SidebarMenu(1)};
        menus[1].available=[enabled](const auto&){return enabled;};
        ExtrudePanel extrude;extrude.enter(menus);
        extrude.refresh(menus,42,1,"EXTRUDE FROM XY","BOTH",true,6,false,false,"READY TO EXTRUDE");
        pages(menus[1]);extrude.exit(menus);
        MovePanel move;move.enter(menus);move.refresh(menus,"cluster","READY");pages(menus[1]);move.exit(menus);
        for(bool twist:{false,true}) {
            BendPanel bend;bend.twist=twist;bend.enter(menus);
            ToolConfigurationDraft config;(void)config.bind(twist?ToolMode::twist:ToolMode::bend,"cluster:1","cluster",{"owner:1"});
            (void)config.setPlaneBp("a",0);(void)config.setPlaneBp("b",42);
            for(bool expanded:{false,true}) {
                bend.clustersOpen=expanded;bend.clusters={"Cluster 1","Cluster 2","Cluster 3","Cluster 4","Cluster 5"};
                for(size_t page:{0U,4U}) {bend.clusterPage=page;bend.refresh(menus,config,"READY");check(menus[1]);}
            }
            bend.exit(menus);
        }
        DimensionPanel dimensions;dimensions.action("dimension:toggle",menus,.01F);
        for(int n:{0,1,17}) {
            dimensions.tool.entries.clear();for(int i=0;i<n;++i)dimensions.tool.create();
            dimensions.refresh(menus,.01F);pages(menus[1]);
        }
        dimensions.exit(menus);
        ViewVolumePanel volumes;volumes.active=true;volumes.connected=true;
        for(int n:{0,1,17}) {
            volumes.entries.clear();for(int i=0;i<n;++i){ViewVolumeRecord e;e.id=std::to_string(i);e.name="Saved volume";volumes.entries.push_back(e);}
            volumes.refresh(menus);pages(menus[1]);
        }
    }
    SidebarMenu menu(0);menu.selected=1;SimulationPanel sim;sim.bind(menu);sim.version=1;
    sim.engines={{"e:cando","CanDo","",true,true},{"e:snupi","SNUPI","",true,false}};
    for(bool selected:{false,true})for(int n:{0,1,20}) {
        sim.selected=selected;sim.jobs.clear();sim.views.clear();
        for(int i=0;i<n;++i){sim.jobs.push_back({"j:"+std::to_string(i),"Completed job","",true,false});sim.views.push_back({"v:"+std::to_string(i),"Predicted shape","",true,false});}
        for(size_t offset=0;offset<size_t(std::max(n,1));offset+=7){sim.jobOffset=sim.viewOffset=offset;check(menu);}
    }
    std::cout<<layouts<<" menu layouts passed spacing, text, target and tool alignment checks\n";
}
