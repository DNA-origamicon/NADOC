#pragma once
#include "sidebar_menu.hpp"
#include <fstream>
#include <iomanip>

namespace nadoc_vr {
// Browser-owned actions and dialogs; no native mutation of the design/history.
class RoutingPanel {
 public:
    struct Row { std::string id,label,detail; bool enabled=false,active=false; };
    int version=0,acknowledged=0,sequence=0,requestedVersion=0;
    unsigned frames=0;
    std::string requested,title;
    std::vector<Row> roots,controls;
    bool available(const std::string& action) const {
        if(!action.starts_with("routing:") || !version || sequence>acknowledged)return false;
        const auto& rows=title.empty()?roots:controls;
        for(const auto& row:rows)if(action=="routing:"+row.id)return row.enabled;
        return false;
    }
    bool active(const std::string& action) const {
        for(const auto* rows:{&roots,&controls})for(const auto& row:*rows)if(action=="routing:"+row.id)return row.active;
        return false;
    }
    bool activate(const std::string& action) {
        if(!available(action))return false;
        requested=action.substr(8);requestedVersion=version;++sequence;return true;
    }
    bool poll(const std::string& path,SidebarMenu& popup,const SidebarMenu& parent) {
        if(path.empty() || ++frames%15)return false;
        std::ifstream in(path+".routing");std::string magic,nextTitle;int v,a,nr,nc;
        if(!(in>>magic>>v>>a>>nr>>nc>>std::quoted(nextTitle))||magic!="NADOC_ROUTING_1"||v<1||a<0||nr<0||nr>20||nc<0||nc>1000)return false;
        if(v==version&&a==acknowledged)return false;
        std::vector<Row> r,c;
        for(auto pair:{std::pair{nr,&r},std::pair{nc,&c}})for(int i=0;i<pair.first;++i){Row row;int en,ac;if(!(in>>std::quoted(row.id)>>std::quoted(row.label)>>std::quoted(row.detail)>>en>>ac)||row.id.size()>100||row.label.size()>250||row.detail.size()>250||(en!=0&&en!=1)||(ac!=0&&ac!=1))return false;row.enabled=en;row.active=ac;pair.second->push_back(row);}
        std::string extra;if(in>>extra)return false;
        const bool opening=title.empty()&&!nextTitle.empty();
        if(title!=nextTitle){popup.offsets[popup.selected]=0;popup.focus.reset();}
        roots=std::move(r);controls=std::move(c);title=nextTitle;version=v;acknowledged=a;
        popup.open=!title.empty();
        if(opening){popup.placement=parent.placement;popup.placement.openDocked(parent.placement.worldPoint({0,0,.045F}),parent.placement.orientation());popup.placement.setScale(parent.placement.scale());}
        SidebarTab tab{1,"routing-dialog",title,{}};
        tab.rows.push_back({"routing-title",title,"","",{}});
        const auto back=std::find_if(controls.begin(),controls.end(),[](const auto& row){return row.label=="Cancel"||row.label=="Done"||row.id=="dismiss";});
        const auto info=std::find_if(controls.begin(),controls.end(),[](const auto& row){return row.id.starts_with("info-");});
        if(back!=controls.end())tab.rows.push_back({"routing:"+back->id,back->label,"","routing:"+back->id,{}});
        else tab.rows.push_back({"routing-back","Please wait...","","",{}});
        tab.rows.push_back({"routing-help",info!=controls.end()?info->label:"Point and trigger to choose","","",{}});
        for(auto it=controls.begin();it!=controls.end();++it)if(it!=back && it!=info)tab.rows.push_back({"routing:"+it->id,it->label,"","routing:"+it->id,{}});
        popup.customTab=std::move(tab);
        const size_t total=popup.total();if(popup.offset()>=total)popup.offsets[popup.selected]=0;
        return true;
    }
};
}
