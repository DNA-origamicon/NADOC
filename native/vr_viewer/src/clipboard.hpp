#pragma once
#include "interaction.hpp"
#include <ostream>

namespace nadoc_vr {
// Immutable, bounded line geometry; no scene rebuilds or GPU allocations on hand motion.
class ClipboardPreview {
public:
    using Segment=std::pair<glm::vec3,glm::vec3>;
    std::vector<Segment> segments;
    std::vector<std::string> owners;
    glm::mat4 copyFrame{1}, placement{1}, committed{1};
    glm::vec3 center{};
    glm::quat orientation{1,0,0,0};
    bool active=false, awaiting=false;
    std::string action;
    bool copy(std::vector<Segment> lines,std::vector<std::string> tokens,
              const HandPose& hand,const glm::mat4& frame) {
        if(!hand.valid || tokens.empty())return false;
        segments=std::move(lines);owners=std::move(tokens);copyFrame=frame;
        glm::vec3 lo(std::numeric_limits<float>::max()),hi(-std::numeric_limits<float>::max());
        for(auto& [a,b]:segments)for(auto p:{a,b}){lo=glm::min(lo,p);hi=glm::max(hi,p);}
        center=segments.empty()?glm::vec3(0):(lo+hi)*.5F;orientation=hand.orientation;active=true;
        update(hand);action="copy";awaiting=true;return true;
    }
    void confirm(const std::vector<Segment>& sourceLines,const HandPose& hand) {
        if(!awaiting || action!="copy")return;
        segments.clear();
        glm::vec3 lo(std::numeric_limits<float>::max()),hi(-std::numeric_limits<float>::max());
        for(const auto& [a,b]:sourceLines) {
            auto x=glm::vec3(copyFrame*glm::vec4(a,1)),y=glm::vec3(copyFrame*glm::vec4(b,1));
            segments.emplace_back(x,y);lo=glm::min(lo,glm::min(x,y));hi=glm::max(hi,glm::max(x,y));
        }
        if(segments.empty()){active=false;return;}
        center=(lo+hi)*.5F;update(hand);
    }
    void update(const HandPose& hand) {
        if(!active || !hand.valid || (awaiting && action=="paste"))return;
        placement=glm::translate(glm::mat4(1),hand.position+hand.orientation*glm::vec3(0,0,-.12F))
            *glm::mat4_cast(hand.orientation*glm::inverse(orientation))
            *glm::translate(glm::mat4(1),-center);
    }
    bool paste(const HandPose& hand,const glm::mat4& frame) {
        if(!active || awaiting || !hand.valid)return false;
        update(hand);committed=glm::inverse(frame)*placement*copyFrame;
        action="paste";awaiting=true;return true;
    }
    void acknowledge(bool waiting,const std::string& status) {
        if(!awaiting || waiting)return;
        awaiting=false;
        if((action=="copy" && status!="created") || (action=="paste" && status=="created"))active=false;
    }
    template<class Line> void draw(Line line) const {
        if(!active)return;
        for(const auto& [a,b]:segments)line(glm::vec3(placement*glm::vec4(a,1)),glm::vec3(placement*glm::vec4(b,1)),glm::vec3(.35F,1.F,.75F));
    }
    void event(std::ostream& out) const {
        out<<",\"owners\":[";
        for(size_t i=0;i<owners.size();++i){if(i)out<<',';out<<'"'<<owners[i]<<'"';}
        out<<"],\"matrix\":[";
        for(size_t c=0;c<4;++c)for(size_t r=0;r<4;++r){if(c||r)out<<',';out<<committed[c][r];}
        out<<']';
    }
    void observe(std::ostream& out) const {
        out<<",\"clipboard\":{\"active\":"<<(active?"true":"false")<<",\"awaiting\":"<<(awaiting?"true":"false")<<",\"segments\":"<<segments.size()<<",\"center\":[";
        const auto p=glm::vec3(placement*glm::vec4(center,1));out<<p.x<<','<<p.y<<','<<p.z<<"]}";
    }
};
}
