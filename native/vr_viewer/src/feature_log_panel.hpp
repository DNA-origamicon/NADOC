#pragma once
#include "sidebar_menu.hpp"
#include <fstream>
#include <iomanip>
#include <tuple>

namespace nadoc_vr {
class FeatureLogPanel {
 public:
    struct Row {std::string id,label;bool enabled=false,active=false,edit=false,revert=false,remove=false,expand=false;};
    struct Target {std::string id,label;bool enabled=false,active=false;};
    std::vector<Row> rows;
    std::vector<Target> targets;
    SidebarMenu* menu=nullptr;
    int version=0,acknowledged=0,sequence=0,requestedVersion=0;
    std::string requested,title="Feature history",status="Waiting for desktop...";
    bool busy=false;
    size_t offset=0;
    int preview=-1,start=-1,dragVersion=0;
    unsigned frames=0;
    static constexpr size_t page=6;
    bool owns() const {return menu && menu->tab().key=="feature-log";}
    template<class R,class... A,class F> void route(std::function<R(A...)>& slot,F callback){
        auto previous=slot;slot=[this,previous,callback](A... args)->R{if(owns())return callback(args...);return previous(args...);};
    }
    void bind(SidebarMenu& m){menu=&m;
        route(m.dynamic,[]{return true;});
        route(m.dynamicPage,[]{return page;});
        route(m.dynamicTotal,[this]{return rows.size();});route(m.dynamicOffset,[this]{return offset;});
        route(m.dynamicBounds,[]{return MenuPanelBounds{{-.515F,-.735F},{.96F,.735F}};});
        route(m.dynamicControls,[this](bool){return controls();});
        route(m.dynamicScroll,[this](int d){scroll(d*int(page));});
        route(m.dynamicScrollAt,[this](glm::vec2,int d){scroll(d);});
        route(m.dynamicScrollTo,[this](const std::string&,float y){offset=size_t(std::round(std::clamp((.38F-y)/.80F,0.F,1.F)*maximum()));});
        route(m.dynamicThumb,[this](const std::string&){const float h=.80F*std::min(1.F,float(page)/std::max(size_t(1),rows.size()));const float top=.38F-(.80F-h)*(maximum()?float(offset)/maximum():0);return MenuPanelBounds{{.782F,top-h},{.816F,top}};});
        route(m.dynamicNavigate,[this](glm::vec2 axis){navigate(axis);});
        m.historyScrub=[this](float y,bool release){return scrub(y,release);};
        m.historyScrubCancel=[this]{preview=start=-1;dragVersion=0;};
    }
    size_t maximum() const {return rows.size()>page?rows.size()-page:0;}
    void scroll(int delta){offset=size_t(std::clamp(int(offset)+delta,0,int(maximum())));}
    int current() const {for(size_t i=0;i<rows.size();++i)if(rows[i].active)return int(i);return -1;}
    bool ready() const {return version>0 && !busy && sequence<=acknowledged;}
    std::string scrub(float y,bool release){
        if(!ready() || rows.empty()){preview=start=-1;return {};}
        if(dragVersion==0){start=current();dragVersion=version;}
        if(dragVersion!=version){preview=start=-1;return {};}
        preview=std::clamp(int(offset)+int(std::round((.325F-y)/.13F)),0,int(rows.size())-1);
        // Holding beyond the rail edge reveals adjacent history without seeking.
        if(!release && y>.41F)scroll(-1);
        if(!release && y<-.44F)scroll(1);
        if(!release)return {};
        const int chosen=preview;preview=-1;dragVersion=0;
        if(chosen==start){start=-1;return {};}
        start=-1;return rows[chosen].enabled?"history:"+rows[chosen].id:std::string{};
    }
    std::vector<SidebarControl> controls() const {
        std::vector<SidebarControl> out;
        auto add=[&](std::string id,std::string label,std::string action,MenuPanelBounds b,bool enabled,bool active=false,std::string icon=""){
            out.push_back({std::move(id),std::move(label),"",std::move(action),b,enabled,active,false,std::move(icon)});};
        add("history:title",title,"",{{-.269F,.53F},{.82F,.65F}},false);
        std::string context="CURRENT DOCUMENT";int selected=-1;for(size_t i=0;i<targets.size();++i)if(targets[i].active){context=targets[i].label;selected=int(i);}
        add("history:target",context,targets.empty()?"":"history:"+targets[size_t((selected+1)%int(targets.size()))].id,{{-.269F,.412F},{.82F,.51F}},ready()&&!targets.empty());
        const MenuPanelBounds viewport{{-.185F,-.408F},{.745F,.38F}};
        for(size_t i=offset;i<std::min(offset+page,rows.size());++i){const auto& row=rows[i];const auto suffix=row.id.substr(2);const float top=.38F-float(i-offset)*.13F;
            const bool active=preview>=0?preview==int(i):row.active;
            add("history:row:"+suffix,row.label,"history:"+row.id,{{-.153F,top-.108F},{.39F,top}},ready()&&row.enabled,active);
            out.back().viewport=viewport;
            int column=0;for(const auto& [name,enabled,icon]:std::array<std::tuple<const char*,bool,const char*>,3>{{{"edit",row.edit,"edit"},{"revert",row.revert,"revert"},{"delete",row.remove,"x"}}}){
                const float x=.402F+column++*.115F;add("history:"+std::string(name)+":"+suffix,name,"history:a:"+suffix+":"+name,{{x,top-.108F},{x+.10F,top}},ready()&&enabled,false,icon);out.back().viewport=viewport;
            }
        }
        add("history:scroll","Scroll history","",{{.766F,-.42F},{.828F,.38F}},rows.size()>page);
        add("history:scrub","Drag to state; release to load","",{{-.269F,-.408F},{-.201F,.38F}},ready()&&!rows.empty());
        const int selectedRow=preview>=0?preview:current();
        if(selectedRow>=int(offset)&&selectedRow<int(offset+page)){
            const float y=.326F-float(selectedRow-int(offset))*.13F;
            out.back().drawingBounds=MenuPanelBounds{{-.264F,y-.018F},{-.206F,y+.018F}};
        }
        add("history:status",preview>=0?"RELEASE: "+rows[size_t(preview)].label:status,"",{{-.269F,-.525F},{.82F,-.435F}},false);
        const auto at=current();
        if(at>=0 && rows[size_t(at)].expand)add("history:expand","Expand / collapse sub-steps","history:a:"+rows[size_t(at)].id.substr(2)+":expand",{{.405F,-.657F},{.82F,-.585F}},ready());
        return out;
    }
    void navigate(glm::vec2 axis){
        if(menu->focus.id=="history:scroll" && std::abs(axis.y)>std::abs(axis.x)){scroll(axis.y>0?-1:1);return;}
        auto items=menu->controls(false);auto at=std::find_if(items.begin(),items.end(),[&](auto& c){return c.id==menu->focus.id;});if(at==items.end())return;
        if(menu->focus.id.starts_with("history:row:") && std::abs(axis.y)>std::abs(axis.x)){
            const int next=std::stoi(menu->focus.id.substr(12))+(axis.y>0?-1:1);if(next<0 || next>=int(rows.size()))return;
            if(next<int(offset))offset=size_t(next);else if(next>=int(offset+page))offset=size_t(next)-page+1;
            menu->focus.id="history:row:"+std::to_string(next);return;
        }
        const auto center=[](const auto& c){return (c.bounds.minimum+c.bounds.maximum)*.5F;};const auto origin=center(*at);float best=1e9F;
        for(const auto& c:items){const auto delta=center(c)-origin;const bool horizontal=std::abs(axis.x)>std::abs(axis.y);const float along=horizontal?delta.x:delta.y,cross=horizontal?delta.y:delta.x;
            if(along*(horizontal?axis.x:axis.y)<=.01F)continue;
            const float cost=std::abs(along)+5*std::abs(cross);if(cost<best){best=cost;menu->focus.id=c.id;}}
    }
    bool activate(const std::string& action){
        if(!action.starts_with("history:") || !ready())return false;
        const auto items=controls();if(std::none_of(items.begin(),items.end(),[&](const auto& c){return c.action==action&&c.enabled;})){
            // Scrub can release on a state just beyond the last fully visible row.
            if(!action.starts_with("history:r:"))return false;
            const auto id=action.substr(8);if(std::none_of(rows.begin(),rows.end(),[&](const auto& r){return r.id==id&&r.enabled;}))return false;
        }
        requested=action.substr(8);requestedVersion=version;++sequence;return true;
    }
    bool poll(const std::string& path){
        if(path.empty() || ++frames%15)return false;
        std::ifstream in(path+".feature-log");std::string magic,t,s;int v,a,b,n,nt;
        if(!(in>>magic>>v>>a>>b>>n>>nt>>std::quoted(t)>>std::quoted(s)) || magic!="NADOC_FEATURE_LOG_1" || v<1||a<0||b<0||b>1||n<0||n>10000||nt<0||nt>10000)return false;
        if(v==version&&a==acknowledged)return false;
        std::vector<Row> next;std::vector<Target> target;
        for(int i=0;i<n;++i){Row r;int e,active,edit,revert,del,expand;if(!(in>>std::quoted(r.id)>>std::quoted(r.label)>>e>>active>>edit>>revert>>del>>expand)||r.id!="r:"+std::to_string(i)||r.label.size()>250)return false;
            for(int flag:{e,active,edit,revert,del,expand})if(flag<0||flag>1)return false;
            r.enabled=e;r.active=active;r.edit=edit;r.revert=revert;r.remove=del;r.expand=expand;next.push_back(r);}
        for(int i=0;i<nt;++i){Target row;int e,active;if(!(in>>std::quoted(row.id)>>std::quoted(row.label)>>e>>active)||row.id!="t:"+std::to_string(i)||e<0||e>1||active<0||active>1)return false;row.enabled=e;row.active=active;target.push_back(row);}
        std::string extra;if(in>>extra)return false;
        const auto old=current();rows=std::move(next);targets=std::move(target);title=t;status=s;busy=b;version=v;acknowledged=a;preview=start=-1;
        offset=std::min(offset,maximum());const int selected=current();
        if(selected>=0&&selected!=old){if(selected<int(offset))offset=size_t(selected);else if(selected>=int(offset+page))offset=size_t(selected)-page+1;}
        return true;
    }
};
}
