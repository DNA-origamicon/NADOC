#pragma once
#include "dimensions.hpp"
#include <fstream>
#include <map>
#include <set>
#include <filesystem>

namespace nadoc_vr {
// Atomic, acknowledged journal. Coordinates here are export/view-space nm;
// the backend reverses the launch camera rotation before storing desktop points.
class DimensionSync {
    std::string path_, prefix_;
    uint64_t sequence_=0;
    glm::vec3 origin_{};
    std::map<std::string,std::string> saved_;
    std::vector<std::pair<uint64_t,std::string>> pending_;
    std::string record(const Dimensions::Entry& e,glm::vec3 center,float scale) const {
        std::ostringstream s; s<<std::setprecision(9);
        s<<"{\"id\":\""<<e.key<<"\",\"name\":"<<std::quoted(e.name)<<",\"visible\":"<<(e.visible?"true":"false");
        for(size_t h=0;h<2;++h) {
            auto p=(e.points[h]-origin_)/scale+center;
            s<<(h==0?",\"a\":[":",\"b\":[")<<p.x<<','<<p.y<<','<<p.z<<']';
        }
        s<<'}';return s.str();
    }
 public:
    void initialize(const std::string& eventPath,Dimensions& tool,glm::vec3 center,float scale,glm::vec3 origin) {
        origin_=origin;
        if(eventPath.empty())return;
        std::ifstream input(eventPath+".dimensions-seed");
        std::string magic;size_t count=0;
        if(!(input>>magic>>prefix_>>count) || magic!="NADOC_DIMENSIONS_1" || count>2048)return;
        std::vector<Dimensions::Entry> loaded;
        for(size_t i=0;i<count;++i) {
            Dimensions::Entry e{unsigned(i+1)};int visible;
            if(!(input>>e.key>>std::quoted(e.name)>>visible))return;
            e.visible=visible!=0;e.attached={false,false};e.valid={true,true};
            for(auto& p:e.points) {
                if(!(input>>p.x>>p.y>>p.z) || !std::isfinite(p.x)||!std::isfinite(p.y)||!std::isfinite(p.z))return;
                p=(p-center)*scale+origin_;
            }
            loaded.push_back(e);
        }
        path_=eventPath;tool.persistenceConnected=true;tool.entries=std::move(loaded);tool.nextId=unsigned(count+1);
        for(const auto& e:tool.entries)saved_[e.key]=record(e,center,scale);
    }
    void update(Dimensions& tool,glm::vec3 center,float scale) {
        if(path_.empty())return;
        uint64_t acknowledged=0;std::ifstream(path_+".dimensions-ack")>>acknowledged;
        std::erase_if(pending_,[&](const auto& p){return p.first<=acknowledged;});
        std::set<std::string> present;
        bool changed=false;
        for(auto& e:tool.entries) {
            if(e.key.empty()) {e.key="vr_"+prefix_+"_"+std::to_string(e.id);e.name="Dimension "+std::to_string(e.id);}
            present.insert(e.key);
            if(!e.valid[0]||!e.valid[1]||e.attached[0]||e.attached[1])continue;
            auto value=record(e,center,scale);
            if(saved_.contains(e.key)&&saved_[e.key]==value)continue;
            saved_[e.key]=value;
            pending_.push_back({++sequence_,"\"upsert\":"+value});changed=true;
        }
        for(auto it=saved_.begin();it!=saved_.end();) {
            if(present.contains(it->first)){++it;continue;}
            pending_.push_back({++sequence_,"\"delete\":\""+it->first+"\""});changed=true;it=saved_.erase(it);
        }
        tool.savePending=!pending_.empty();
        if(!changed && pending_.empty())return;
        std::ofstream output(path_+".dimensions-pending.tmp");output<<'[';
        bool first=true;for(const auto& [seq,value]:pending_) {if(!first)output<<',';first=false;output<<"{\"sequence\":"<<seq<<','<<value<<'}';}
        output<<']';output.close();
        if(output) {std::error_code error;std::filesystem::rename(path_+".dimensions-pending.tmp",path_+".dimensions-pending",error);}
    }
};
}
