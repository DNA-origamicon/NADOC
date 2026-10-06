#include "bend_panel.hpp"
#include "extrude_panel.hpp"
#include "move_panel.hpp"
#include "dimension_panel.hpp"
#include "view_volume_panel.hpp"
#include "simulation_panel.hpp"
#include "trajectory_panel.hpp"
#include "lattice_painter.hpp"
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
            const float right=menu.tab().key=="extrude" && y<.261F && y>menu.footerY()?ui_style::toolHalfWidth-.080F:ui_style::toolHalfWidth;
            if(std::abs(b.minimum.x+ui_style::toolHalfWidth)>kMenuLayoutEpsilon || std::abs(b.maximum.x-right)>kMenuLayoutEpsilon)
                throw std::runtime_error(menu.tab().key+": row does not align to content rails");
        }
    }
    ++layouts;
}
static void pages(SidebarMenu& menu) {
    menu.offsets[menu.selected]=0;
    const size_t last=menu.total()>menu.pageRows()?menu.total()-menu.pageRows():0;
    for(size_t offset=1;offset<=last;++offset) {
        menu.offsets[menu.selected]=offset;
        double now=10;menu.animationClock=[&]{return now;};menu.rowScroll={float(offset-1),float(offset),now};
        for(double phase:{.025,.10,.175}) {now=10+phase;check(menu);}
    }
    menu.rowScroll={};menu.offsets[menu.selected]=0;menu.animationClock=SidebarScroll::now;
    do {
        check(menu);
        const auto controls=menu.controls(false);
        for(auto state:{GripFrameState::moving,GripFrameState::resizing}) {
            menu.gripState=state;
            menu.focus.begin(menu.canScroll(-1)||menu.canScroll(1)?"scrollbar":controls.front().id,"");
            menu.hovered=menu.pressed=controls.front().id;check(menu);
        }
        menu.gripState=GripFrameState::idle;menu.focus.reset();menu.hovered.clear();menu.pressed.clear();
        if(!menu.canScroll(1))break;menu.scroll(1);
    }while(true);
}
int main() {
    for(bool square:{false,true})for(size_t count:{0U,8U,16641U}) {
        const auto audit=drawLatticePainterChrome({"XY",square,false,false,count,count},
            [](glm::vec3,glm::vec3,glm::vec3){},[](MenuPanelBounds,glm::vec3){},
            [](const std::string&,float,float,float,glm::vec3){});
        if(!audit.valid())throw std::runtime_error("painter: "+audit.summary());
        const auto& labels=audit.texts();
        for(size_t i=0;i<labels.size();++i) {
            assert(menuLayoutContains(kLatticePainterContent,labels[i].bounds));
            assert(!menuLayoutIntersects(kLatticePainterGrid,labels[i].bounds));
            for(size_t j=0;j<i;++j)assert(!menuLayoutIntersects(labels[i].bounds,labels[j].bounds));
        }
        // A crowded footer label must be detected by the same geometry checker.
        assert(!menuLayoutContains(kLatticePainterContent,
            strokeTextLayoutBounds("CENTER PAINT",-.05F,-.282F,.0025F)));
        ++layouts;
    }
    for(int hand:{0,1})for(bool assembly:{false,true}) {
        SidebarMenu menu(hand,assembly);
        for(size_t i=0;i<menu.tabs.size();++i){
            menu.selected=i;pages(menu);
            for(const auto& row:menu.tab().rows)if(row.action.starts_with("section:"))menu.collapsed.insert(row.id);
            pages(menu);menu.collapsed.clear();
            menu.label=[](const auto& action,const auto& fallback){return action=="qr:status"||action=="qr:cube-status"||action=="share:status"?std::string(250,'W'):fallback;};
            menu.loadingProgress=[](const auto& action)->std::optional<std::pair<float,std::string>> {return action.starts_with("repr:")?std::optional(std::pair{1.2F,std::string(250,'W')}):std::nullopt;};
            pages(menu);menu.label=[](const auto&,const auto& fallback){return fallback;};menu.loadingProgress=[](const auto&){return std::optional<std::pair<float,std::string>>{};};
        }
    }
    for(bool enabled:{false,true}) {
        std::array<SidebarMenu,2> menus{SidebarMenu(0),SidebarMenu(1)};
        menus[1].available=[enabled](const auto&){return enabled;};
        ExtrudePanel extrude;extrude.enter(menus);
        extrude.refresh(menus,1000000,-1,"EXTRUDE FROM YZ","SCAFFOLD",true,16641,true,false,std::string(250,'W'));
        pages(menus[1]);extrude.exit(menus);
        MovePanel move;move.enter(menus);move.refresh(menus,"cluster",std::string(250,'W'));pages(menus[1]);move.exit(menus);
        for(bool twist:{false,true}) {
            BendPanel bend;bend.twist=twist;bend.enter(menus);
            ToolConfigurationDraft config;(void)config.bind(twist?ToolMode::twist:ToolMode::bend,"cluster:1","cluster",{"owner:1"});
            (void)config.setPlaneBp("a",-100000);(void)config.setPlaneBp("b",100000);
            for(bool expanded:{false,true}) {
                bend.clustersOpen=expanded;bend.clusterLabel=std::string(250,'W');bend.clusters=std::vector<std::string>(5,std::string(250,'W'));
                for(size_t page:{0U,4U}) {bend.clusterPage=page;bend.refresh(menus,config,std::string(250,'W'));pages(menus[1]);}
            }
            bend.clustersOpen=false;
            for(bool manual:{false,true})for(bool elements:{false,true}) {
                bend.manual=manual;bend.elements=elements;
                if(twist){(void)config.cycleOption();config.setTwist(-36000);}
                else config.setBend(manual?.001:359.0,359.0);
                bend.refresh(menus,config,"PLANE 2 FIXED / RELEASE TO FINISH");pages(menus[1]);
            }
            bend.exit(menus);
        }
        DimensionPanel dimensions;dimensions.action("dimension:toggle",menus,.01F);
        for(int n:{0,1,17}) {
            dimensions.tool.entries.clear();for(int i=0;i<n;++i){dimensions.tool.create();dimensions.tool.entries.back().name=std::string(250,'W');}
            dimensions.refresh(menus,.01F);pages(menus[1]);
        }
        dimensions.exit(menus);
        ViewVolumePanel volumes;volumes.active=true;volumes.connected=true;
        for(int n:{0,1,17}) {
            volumes.entries.clear();for(int i=0;i<n;++i){ViewVolumeRecord e;e.id=std::to_string(i);e.name=std::string(250,'W');volumes.entries.push_back(e);}
            volumes.refresh(menus);pages(menus[1]);
        }
    }
    for(bool active:{false,true})for(uint32_t count:{0U,1U,4294967295U}) {
        std::array<SidebarMenu,2> menus{SidebarMenu(0),SidebarMenu(1)};
        TrajectoryState state;state.active=active;state.frameCount=count;state.frameIndex=count?count-1:0;
        state.speed=8;state.stride=100000;state.playing=state.live=state.loop=true;
        TrajectoryPanel trajectory;trajectory.enter(menus,state);pages(menus[0]);trajectory.exit(menus);
    }
    SidebarMenu menu(0);menu.selected=1;SimulationPanel sim;sim.bind(menu);sim.version=1;
    sim.engines={{"e:cando","CanDo","",true,true},{"e:snupi","SNUPI","",true,false},{"e:mrdna","mrDNA","",false,false},{"e:oxdna","oxDNA","",true,false},{"e:namd","NAMD","",true,false}};
    for(bool selected:{false,true})for(int n:{0,1,20}) {
        sim.selected=selected;sim.jobs.clear();sim.views.clear();
        for(int i=0;i<n;++i){sim.jobs.push_back({"j:"+std::to_string(i),std::string(250,'W'),"",true,false});sim.views.push_back({"v:"+std::to_string(i),std::string(250,'W'),"",true,false});}
        for(size_t offset=0;offset<size_t(std::max(n,1));offset+=7){sim.jobOffset=sim.viewOffset=offset;check(menu);}
        if(n>7)for(size_t offset=1;offset<=size_t(n)-7;++offset) {
            sim.jobOffset=sim.viewOffset=offset;double now=10;menu.animationClock=[&]{return now;};
            sim.jobScroll=sim.viewScroll={float(offset-1),float(offset),now};
            for(double phase:{.025,.10,.175}){now=10+phase;check(menu);}
            menu.animationClock=SidebarScroll::now;
        }
    }
    std::cout<<layouts<<" menu layouts passed spacing, text, target and tool alignment checks\n";
}
