#pragma once
#include "sidebar_menu.hpp"
#include <fstream>
#include <iomanip>

namespace nadoc_vr {
class SimulationPanel {
 public:
    struct Row {std::string id,label,detail;bool enabled=false,active=false;};
    unsigned pollFrames=0;
    int version=0,acknowledged=0,sequence=0,requestedVersion=0;
    std::string requested;
    bool selected=false;
    std::vector<Row> engines,jobs,views;
    size_t jobOffset=0,viewOffset=0;
    SidebarScroll jobScroll,viewScroll;
    SidebarMenu* menu=nullptr;
    SidebarMenu* adjacent=nullptr;
    static constexpr size_t page=7;
    void bind(SidebarMenu& target,SidebarMenu* right=nullptr) {
        adjacent=right;
        menu=&target;target.dynamic=[]{return true;};
        target.dynamicTotal=[this]{return jobs.size();};target.dynamicOffset=[this]{return jobOffset;};
        target.dynamicControls=[this](bool animated){return controls(animated);};
        target.dynamicBounds=[this]{return MenuPanelBounds{{-.515F,-.735F},{selected?1.56F:.80F,.735F}};};
        target.dynamicNavigate=[this](glm::vec2 axis){navigate(axis);};
        target.dynamicScrollAt=[this](glm::vec2 p,int d){scroll(p.x>.78F,d);};
        target.dynamicScroll=[this](int d){scroll(menu->focus.id.starts_with("sim:scroll:views") || menu->focus.id.starts_with("sim:v:") || menu->hovered.starts_with("sim:v:"),d);};
        target.dynamicScrollTo=[this](const std::string& id,float y){const bool right=id=="sim:scroll:views";auto& offset=right?viewOffset:jobOffset;const size_t count=right?views.size():jobs.size();if(count>page){const float half=.84F*float(page)/count*.5F;offset=size_t(std::round(std::clamp((.36F-half-y)/(.84F-2*half),0.F,1.F)*((count-1)/page)))*page;}};
        target.dynamicThumb=[this](const std::string& id){const bool right=id=="sim:scroll:views";auto b=scrollBounds(right);const size_t n=right?views.size():jobs.size(),o=right?viewOffset:jobOffset;const float h=.84F*std::min(1.F,float(page)/std::max(size_t(1),n));const size_t last=n>page?n-page:0;const float top=b.maximum.y-(.84F-h)*(last?std::clamp((right?viewScroll:jobScroll).value(float(o),menu->animationClock())/last,0.F,1.F):0);return MenuPanelBounds{{b.minimum.x+.008F,top-h},{b.maximum.x-.008F,top}};};
    }
    bool poll(const std::string& path) {
        if(path.empty() || ++pollFrames%15)return false;
        std::ifstream in(path+".simulations");std::string magic;int v,a,ne,nj,nv,sel;
        if(!(in>>magic>>v>>a>>ne>>nj>>nv>>sel)||magic!="NADOC_SIMULATIONS_1"||v<1||a<0||ne<0||ne>10||nj<0||nj>10000||nv<0||nv>1000||(sel!=0&&sel!=1))return false;
        if(v==version&&a==acknowledged)return false;
        std::vector<Row> e,j,c;
        for(auto pair:{std::pair{ne,&e},std::pair{nj,&j},std::pair{nv,&c}})for(int i=0;i<pair.first;++i){Row r;int enabled,active;if(!(in>>std::quoted(r.id)>>std::quoted(r.label)>>std::quoted(r.detail)>>enabled>>active)||r.id.size()>100||r.label.size()>250||r.detail.size()>250||(enabled!=0&&enabled!=1)||(active!=0&&active!=1))return false;r.enabled=enabled;r.active=active;pair.second->push_back(r);}
        std::string extra;if(in>>extra)return false;
        const auto active=[](const auto& rows){for(const auto& r:rows)if(r.active)return r.id;return std::string{};};
        if(active(e)!=active(engines)){jobOffset=0;viewOffset=0;}
        if(active(j)!=active(jobs))viewOffset=0;
        if(sel && !selected && adjacent && menu->open && menu->dynamicActive()){adjacent->open=false;adjacent->focus.reset();}
        engines=std::move(e);jobs=std::move(j);views=std::move(c);version=v;acknowledged=a;selected=sel!=0;
        jobOffset=jobs.empty()?0:std::min(jobOffset,(jobs.size()-1)/page*page);viewOffset=views.empty()?0:std::min(viewOffset,(views.size()-1)/page*page);
        if(menu&&menu->focus.active){auto items=menu->controls();if(std::none_of(items.begin(),items.end(),[&](const auto& x){return x.id==menu->focus.id;}))menu->focus.id="sim:jobs";}
        return true;
    }
    static MenuPanelBounds scrollBounds(bool right) {return {{right?1.43F:-.269F,-.48F},{right?1.492F:-.207F,.36F}};}
    void scroll(bool right,int direction) {auto& o=right?viewOffset:jobOffset;const size_t n=right?views.size():jobs.size();if(direction<0)o=o>page?o-page:0;else if(o+page<n)o+=page;}
    void scrollRow(bool right,int direction) {
        auto& offset=right?viewOffset:jobOffset;
        const auto old=offset;
        const auto count=right?views.size():jobs.size();
        if(direction<0 && offset>0)--offset;
        else if(direction>0 && offset+page<count)++offset;
        (right?viewScroll:jobScroll).move(float(old),float(offset),menu->animationClock());
    }
    std::vector<SidebarControl> controls(bool animated=true) const {
        std::vector<SidebarControl> out;
        const bool ready=sequence<=acknowledged;
        for(size_t i=0;i<engines.size();++i){const auto& r=engines[i];const float x=-.269F+i*.202F;out.push_back({"sim:"+r.id,r.label,"","simulation:"+r.id,{{x,.55F},{x+.19F,.65F}},r.enabled&&ready,r.active});}
        out.push_back({"sim:jobs",version?"Jobs":"Waiting for desktop...","","",{{-.19F,.39F},{.73F,.49F}},false});
        out.push_back({"sim:trajectory","Trajectory","","trajectory",{{-.19F,-.561F},{.385F,-.489F}},true});
        if(selected)out.push_back({"sim:frame","Frame result","","recenter",{{.81F,-.657F},{1.41F,-.585F}},true});
        if(selected)out.push_back({"sim:views","Visualizations","","",{{.81F,.39F},{1.41F,.49F}},false});
        for(bool right:{false,true}) {
            if(right&&!selected)continue;
            const auto& rows=right?views:jobs;const size_t offset=right?viewOffset:jobOffset;
            const float position=animated?(right?viewScroll:jobScroll).value(float(offset),menu->animationClock()):float(offset);
            for(size_t i=size_t(std::floor(position));i<std::min(size_t(std::ceil(position))+page,rows.size());++i) {
                const auto& r=rows[i];const float y=.30F-(float(i)-position)*.12F;
                out.push_back({"sim:"+r.id,r.label,"","simulation:"+r.id,{{right?.81F:-.19F,y-.054F},{right?1.41F:.73F,y+.054F}},r.enabled&&ready,r.active});
                out.back().viewport=MenuPanelBounds{{right?.81F:-.19F,-.474F},{right?1.41F:.73F,.354F}};
            }
            const auto id=right?"sim:scroll:views":"sim:scroll:jobs";
            out.push_back({id,"Scroll","","",scrollBounds(right),rows.size()>page});
        }
        return out;
    }
    bool activate(const std::string& action) {
        if(!action.starts_with("simulation:")||sequence>acknowledged||version==0)return false;
        requested=action.substr(11);requestedVersion=version;++sequence;return true;
    }
    void navigate(glm::vec2 axis) {
        const auto items=menu->controls(false);auto at=std::find_if(items.begin(),items.end(),[&](const auto& c){return c.id==menu->focus.id;});if(at==items.end())return;
        const bool horizontal=std::abs(axis.x)>std::abs(axis.y);
        if(SidebarMenu::isScrollbar(at->id)&&!horizontal){scrollRow(at->id=="sim:scroll:views",axis.y>0?-1:1);return;}
        if(!horizontal) for(bool right:{false,true}) {
            const auto& rows=right?views:jobs;
            auto current=std::find_if(rows.begin(),rows.end(),[&](const auto& r){return "sim:"+r.id==menu->focus.id;});
            if(current==rows.end())continue;
            const auto index=std::ptrdiff_t(current-rows.begin())+(axis.y>0?-1:1);
            if(index>=0 && index<std::ptrdiff_t(rows.size())) {
                menu->focus.id="sim:"+rows[size_t(index)].id;
                const size_t offset=right?viewOffset:jobOffset;
                if(size_t(index)<offset)scrollRow(right,-1);
                else if(size_t(index)>=offset+page)scrollRow(right,1);
                return;
            }
        }
        const auto center=[](const auto& c){return (c.bounds.minimum+c.bounds.maximum)*.5F;};
        auto origin=center(*at);if(SidebarMenu::isScrollbar(at->id))origin.y=menu->navigationY;else menu->navigationY=origin.y;
        float best=1e9F;const SidebarControl* next=nullptr;
        for(const auto& c:items){if(c.id==at->id)continue;auto point=center(c);float distance;
            if(horizontal){if((axis.x>0?1:-1)*(point.x-origin.x)<=.025F)continue;distance=std::abs(point.x-origin.x)+3*std::abs(point.y-origin.y);if(SidebarMenu::isScrollbar(c.id))distance=std::abs(point.x-origin.x);}
            else {if((axis.y>0?1:-1)*(point.y-origin.y)<=.025F)continue;if(std::min(c.bounds.maximum.x,at->bounds.maximum.x)-std::max(c.bounds.minimum.x,at->bounds.minimum.x)<=.001F)continue;distance=std::abs(point.y-origin.y)+.1F*std::abs(point.x-origin.x);}
            if(distance<best){best=distance;next=&c;}}
        if(next)menu->focus.id=next->id;
    }
};
}
