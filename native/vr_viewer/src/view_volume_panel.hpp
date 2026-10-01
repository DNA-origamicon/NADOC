#pragma once
#include "sidebar_menu.hpp"
#include "view_volume_interaction.hpp"
#include <map>
#include <set>
#include <fstream>
#include <iomanip>
#include <filesystem>
#include <chrono>
#include <tuple>

namespace nadoc_vr {
class ViewVolumePanel {
 public:
    using Entry=ViewVolumeRecord;
    ViewVolumeInteraction interaction;
    std::set<std::string> dirty;
    std::map<std::string,uint64_t> localSequence;
    std::chrono::steady_clock::time_point lastSave{};
    bool active=false, connected=false;
    std::vector<Entry> entries;
    std::array<bool,2> savedOpen{};
    size_t savedOffset=0;
    std::string path;
    uint64_t sequence=0;
    std::vector<std::pair<uint64_t,std::string>> pending;
    std::chrono::steady_clock::time_point lastPoll{};
    void initialize(const std::string& eventPath) {path=eventPath;flushedRange_.reset();}
    void exit(std::array<SidebarMenu,2>& menus) {
        active=false;menus[1].customTab.reset();menus[1].offsets[menus[1].selected]=savedOffset;
        for(size_t h=0;h<2;++h){menus[h].open=savedOpen[h];menus[h].focus.reset();menus[h].hovered.clear();}
    }
    void flush() {
        if(path.empty() || pending.empty())return;
        // Pending operations are immutable and sequences increase monotonically.
        // Retry failed writes, but do not rewrite the same queue every input frame.
        const auto range=std::tuple{pending.front().first,pending.back().first,pending.size()};
        if(flushedRange_==range)return;
        std::ofstream out(path+".volumes-pending.tmp");out<<'[';
        bool first=true;for(const auto& [seq,op]:pending){if(!first)out<<',';first=false;out<<"{\"sequence\":"<<seq<<','<<op<<'}';}
        out<<']';out.close();
        if(out){std::error_code error;std::filesystem::rename(path+".volumes-pending.tmp",path+".volumes-pending",error);if(!error)flushedRange_=range;}
    }
    void update(std::array<SidebarMenu,2>& menus) {
        auto now=std::chrono::steady_clock::now();
        if(now-lastPoll<std::chrono::milliseconds(100))return;
        lastPoll=now;
        std::ifstream in(path+".volumes-state");std::string magic;uint64_t ack;size_t count;
        if(!(in>>magic>>ack>>count)||(magic!="NADOC_VOLUMES_1"&&magic!="NADOC_VOLUMES_2"&&magic!="NADOC_VOLUMES_3")||count>20000)return;
        std::vector<Entry> loaded;
        for(size_t i=0;i<count;++i){
            Entry e;if(!(in>>std::quoted(e.id)>>std::quoted(e.name)>>e.outline>>e.enabled>>e.sides)||(e.sides!=4&&e.sides!=6))return;
            if(magic=="NADOC_VOLUMES_3" && !(in>>std::quoted(e.representation)>>std::quoted(e.coloring)>>e.opacity))return;
            if(magic!="NADOC_VOLUMES_1") {
                if(!(in>>e.center.x>>e.center.y>>e.center.z>>e.half.x>>e.half.y>>e.half.z>>e.rotation.x>>e.rotation.y>>e.rotation.z>>e.rotation.w))return;
                if(!std::isfinite(glm::length(e.center))||!std::isfinite(glm::length(e.half))||glm::any(glm::lessThanEqual(e.half,glm::vec3(0)))||!std::isfinite(glm::length(e.rotation))||std::abs(glm::length(e.rotation)-1)>.001F)return;
                e.editable=true;
            }
            for(size_t j=0;j<e.sides*2;++j){glm::vec3 p;if(!(in>>p.x>>p.y>>p.z))return;e.points.push_back(p);}
            loaded.push_back(std::move(e));
        }
        connected=true;sequence=std::max(sequence,ack);
        std::erase_if(pending,[&](const auto& p){return p.first<=ack;});
        for(auto& remote:loaded) {
            const auto previous=std::find_if(entries.begin(),entries.end(),[&](const auto& e){return e.id==remote.id;});
            if(localSequence.contains(remote.id)&&localSequence[remote.id]<=ack)localSequence.erase(remote.id);
            if(previous!=entries.end() && (interaction.held==remote.id||dirty.contains(remote.id)||localSequence.contains(remote.id))) {
                remote.center=previous->center;remote.half=previous->half;remote.rotation=previous->rotation;remote.points=previous->points;
            }
        }
        entries=std::move(loaded);flush();refresh(menus);
    }
    void saveTransforms(bool force=false) {
        const auto now=std::chrono::steady_clock::now();
        if(!force&&now-lastSave<std::chrono::milliseconds(100))return;
        for(const auto& id:dirty) {
            const auto it=std::find_if(entries.begin(),entries.end(),[&](const auto& e){return e.id==id;});
            if(it==entries.end())continue;
            const auto& e=*it;std::ostringstream op;op<<std::setprecision(9);
            op<<"\"action\":\"transform\",\"id\":"<<std::quoted(e.id)
              <<",\"center\":["<<e.center.x<<','<<e.center.y<<','<<e.center.z<<']'
              <<",\"half\":["<<e.half.x<<','<<e.half.y<<','<<e.half.z<<']'
              <<",\"rotation\":["<<e.rotation.x<<','<<e.rotation.y<<','<<e.rotation.z<<','<<e.rotation.w<<']';
            pending.push_back({++sequence,op.str()});localSequence[id]=sequence;
        }
        dirty.clear();lastSave=now;flush();
    }
    template<class Feedback>
    std::array<bool,2> input(const std::array<HandPose,2>& hands,const std::array<bool,2>& clicked,
            const std::array<bool,2>& pressed,const glm::mat4& model,glm::vec3 center,float scale,glm::vec3 origin,
            bool allowed,bool sceneGrip,Feedback feedback) {
        const bool wasHeld=interaction.hand.has_value();
        auto claimed=interaction.input(entries,hands,clicked,pressed,ViewVolumeInteraction::frame(model,center,scale,origin),
            allowed&&connected,sceneGrip,[&](const auto& e){dirty.insert(e.id);},feedback);
        saveTransforms(wasHeld&&!interaction.hand);
        return claimed;
    }
    bool action(const std::string& action,std::array<SidebarMenu,2>& menus,glm::vec3 center,float scale) {
        if(!action.starts_with("volume:"))return false;
        if(action=="volume:toggle") {
            if(active){exit(menus);return true;}
            for(size_t h=0;h<2;++h){savedOpen[h]=menus[h].open;menus[h].focus.reset();}
            savedOffset=menus[1].offset();menus[1].offsets[menus[1].selected]=0;
            menus[0].open=false;menus[1].open=true;active=true;
        } else if(connected && pending.empty() && !interaction.hand) {
            std::ostringstream op;op<<std::setprecision(9);
            if(action=="volume:new:box" || action=="volume:new:hexagonal") {
                const auto id="vr_volume_"+std::to_string(std::chrono::system_clock::now().time_since_epoch().count());
                op<<"\"action\":\"create\",\"id\":"<<std::quoted(id)<<",\"shape\":"<<std::quoted(action.substr(11))<<",\"center\":["<<center.x<<','<<center.y<<','<<center.z<<"],\"radius\":"<<(.1F/scale);
            } else {
                auto split=action.find(':',7);if(split==std::string::npos)return true;
                auto command=action.substr(7,split-7),id=action.substr(split+1);
                auto it=std::find_if(entries.begin(),entries.end(),[&](const auto& e){return e.id==id;});
                if(it==entries.end() || (command!="delete"&&command!="outline"&&command!="enabled"))return true;
                op<<"\"action\":"<<std::quoted(command)<<",\"id\":"<<std::quoted(id);
                if(command!="delete")op<<",\"value\":"<<((command=="outline"?!it->outline:!it->enabled)?"true":"false");
            }
            pending.push_back({++sequence,op.str()});flush();
        }
        refresh(menus);return true;
    }
    void refresh(std::array<SidebarMenu,2>& menus) {
        if(!active)return;
        SidebarTab tab{1,"view-volumes","View Volumes",{
            {"volume:toggle","View Volumes - Return to menus",!connected?"OPEN A PART TO MANAGE VOLUMES":pending.empty()?"VOLUMES SAVED TO PART":"SAVING VOLUMES","volume:toggle",{}},
            {"volume:new:box","+ Square volume","",connected&&pending.empty()?"volume:new:box":"",{}},
            {"volume:new:hexagonal","+ Hex volume","",connected&&pending.empty()?"volume:new:hexagonal":"",{}}}};
        for(const auto& e:entries)tab.rows.push_back({"volume:entry:"+e.id,e.name,std::string(e.outline?"eye":"eye-off")+(e.enabled?":on":":off"),pending.empty()?"volume:entry:"+e.id:"",{}});
        auto& m=menus[1];m.customTab=std::move(tab);
        m.offsets[m.selected]=std::min(m.offset(),m.total()==0?0:(m.total()-1)/m.pageRows()*m.pageRows());
        if(m.focus.active){auto controls=m.controls();if(std::none_of(controls.begin(),controls.end(),[&](const auto& c){return c.id==m.focus.id;}))m.focus.id=controls.front().id;}
    }
    template<class Line> void draw(const glm::mat4& model,glm::vec3 center,float scale,glm::vec3 origin,Line line) const {
        for(const auto& e:entries)if(e.outline) {
            auto point=[&](size_t i){return glm::vec3(model*glm::vec4((e.points[i]-center)*scale+origin,1));};
            glm::vec3 color=e.enabled?glm::vec3(.27F,.71F,1):glm::vec3(.5F);
            for(size_t i=0;i<e.sides;++i){size_t j=(i+1)%e.sides;line(point(i),point(j),color);line(point(i+e.sides),point(j+e.sides),color);line(point(i),point(i+e.sides),color);}
            if(e.editable) {
                const auto f=ViewVolumeInteraction::frame(model,center,scale,origin);
                const auto c=ViewVolumeInteraction::point(f,e.center);
                const bool hot=interaction.held==e.id || interaction.nearby[0]==e.id || interaction.nearby[1]==e.id;
                const float radius=hot?.014F:.006F;
                const glm::vec3 marker=hot?glm::vec3(1,.8F,.15F):color;
                // A tracking-space octahedron stays legible under scene zoom.
                for(int axis=0;axis<3;++axis)for(int sign:{-1,1})for(int side:{-1,1}) {
                    glm::vec3 a{},b{};a[axis]=radius*float(sign);b[(axis+1)%3]=radius*float(side);line(c+a,c+b,marker);
                }
                if(interaction.held==e.id)for(size_t h=0;h<2;++h)if(interaction.nearbyFace[h]>=0) {
                    const auto indices=e.face(size_t(interaction.nearbyFace[h]));
                    const glm::vec3 highlight{1,.65F,.1F};
                    glm::vec3 middle{};for(auto i:indices)middle+=point(i);middle/=float(indices.size());
                    for(size_t i=0;i<indices.size();++i) {
                        const auto a=point(indices[i]),b=point(indices[(i+1)%indices.size()]);
                        line(a,b,highlight);line(a,middle,highlight);
                        line(glm::mix(a,middle,.15F),glm::mix(b,middle,.15F),highlight);
                    }
                }
            }
        }
    }
 private:
    std::optional<std::tuple<uint64_t,uint64_t,size_t>> flushedRange_;
};
}
