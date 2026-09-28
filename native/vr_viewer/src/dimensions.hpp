#pragma once
#include "interaction.hpp"
#include "stroke_font.hpp"
#include <vector>
#include <sstream>
#include <iomanip>
#include <algorithm>

namespace nadoc_vr {
// Endpoints live in normalized model space, so model presentation never changes nm.
class Dimensions {
 public:
    struct Entry {
        unsigned id;
        std::array<glm::vec3,2> points{};
        std::array<bool,2> attached{true,true}, valid{};
        bool visible=true;
        std::string key{}, name{};
    };
    bool active=false;
    bool persistenceConnected=false, savePending=false;
    unsigned selected=0, nextId=1;
    std::vector<Entry> entries;
    Entry* current() {
        for(auto& entry:entries) if(entry.id==selected) return &entry;
        return nullptr;
    }
    void freeze() { if(auto* e=current()) e->attached={false,false}; }
    void leave() { freeze(); active=false; }
    void create() { freeze(); selected=nextId++; entries.push_back(Entry{selected}); }
    void update(const std::array<HandPose,2>& hands,const glm::mat4& model,bool manipulating) {
        if(!active) return;
        auto* e=current(); if(!e) return;
        // A model grip fixes the live endpoints into the model before moving it.
        if(manipulating) {freeze();return;}
        for(size_t h=0;h<2;++h) if(e->attached[h] && hands[h].valid) {
            auto tip=hands[h].position+hands[h].orientation*glm::vec3(0,0,-.12F);
            e->points[h]=glm::vec3(glm::inverse(model)*glm::vec4(tip,1));
            e->valid[h]=true;
        }
    }
    void trigger(size_t hand) { if(auto* e=current(); active && e && e->valid[hand]) e->attached[hand]=!e->attached[hand]; }
    void select(unsigned id) {freeze();selected=id;}
    void remove(unsigned id) { std::erase_if(entries,[&](const auto& e){return e.id==id;});if(selected==id)selected=0; }
    static float length(const Entry& e,float scale) {return glm::distance(e.points[0],e.points[1])/scale;}
    static std::string label(const Entry& e,float scale) {
        if(!e.valid[0] || !e.valid[1]) return "Waiting for controllers";
        std::ostringstream s;s<<std::fixed<<std::setprecision(3)<<length(e,scale)<<" nm";return s.str();
    }
    template<class Line,class Text>
    void draw(const glm::mat4& model,float scale,const glm::quat& orientation,Line line,Text text) const {
        for(const auto& e:entries) if(e.visible && e.valid[0] && e.valid[1]) {
            const auto a=glm::vec3(model*glm::vec4(e.points[0],1));
            const auto b=glm::vec3(model*glm::vec4(e.points[1],1));
            const glm::vec3 color=active && e.id==selected?glm::vec3(0,.9F,1):glm::vec3(.345F,.65F,1);
            line(a,b,color);
            for(size_t h=0;h<2;++h) {
                const auto center=h==0?a:b;
                const auto marker=e.attached[h]?color:glm::vec3(1,.8F,.3F);
                for(int axis=0;axis<3;++axis) {glm::vec3 delta(0);delta[axis]=.006F;line(center-delta,center+delta,marker);}
            }
            nadoc_vr::MenuPlacement label;
            label.openDocked((a+b)*.5F,orientation);
            const auto value=Dimensions::label(e,scale);
            text(label,value,-strokeTextWidth(value.size(),.0018F)*.5F,.018F,.0018F,color,.002F);
        }
    }
    std::string json(float scale,const glm::mat4& model) const {
        std::ostringstream s;s<<"{\"active\":"<<(active?"true":"false")<<",\"selected\":"<<selected<<",\"entries\":[";
        bool first=true;
        for(const auto& e:entries) {
            if(!first)s<<',';
            first=false;
            s<<"{\"id\":"<<e.id<<",\"visible\":"<<(e.visible?"true":"false")<<",\"length_nm\":"<<length(e,scale)<<",\"endpoints\":[";
            for(size_t h=0;h<2;++h) {
                if(h)s<<',';
                auto p=glm::vec3(model*glm::vec4(e.points[h],1));
                s<<"{\"attached\":"<<(e.attached[h]?"true":"false")<<",\"valid\":"<<(e.valid[h]?"true":"false")<<",\"world\":["<<p.x<<','<<p.y<<','<<p.z<<"]}";
            }
            s<<"]}";
        }
        s<<"]}";return s.str();
    }
};
}
