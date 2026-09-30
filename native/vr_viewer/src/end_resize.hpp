#pragma once
#include "interaction.hpp"
#include <fstream>
#include <optional>

namespace nadoc_vr {
// Controller displacement is measured in model space, so scene scaling never
// changes the number of base pairs represented by a pull.
class EndResize {
 public:
    struct Arrow { glm::vec3 position{}, direction{}, offset{}; };
    std::vector<Arrow> arrows;
    uint64_t version=0, sequence=0, committedVersion=0, waitingVersion=0;
    int minimum=0, maximum=0, delta=0, committedDelta=0;
    std::optional<size_t> hand;
    size_t grabbed=0;
    glm::vec3 start{};
    glm::mat4 startModel{1};
    bool nearby=false;

    void poll(const std::string& path, glm::vec3 center, float scale, glm::vec3 origin) {
        if(path.empty())return;
        std::ifstream input(path+".end-resize");
        std::string magic;uint64_t next;size_t count;int lo,hi;
        if(!(input>>magic>>next>>lo>>hi>>count) || magic!="NADOC_END_RESIZE_1" ||
           count>1024 || lo < -200 || hi>200 || lo>hi || next==version)return;
        std::vector<Arrow> loaded;
        for(size_t i=0;i<count;++i) {
            Arrow a;
            if(!(input>>a.position.x>>a.position.y>>a.position.z>>a.direction.x>>a.direction.y>>a.direction.z>>a.offset.x>>a.offset.y>>a.offset.z))return;
            for(int j=0;j<3;++j)if(!std::isfinite(a.position[j])||!std::isfinite(a.direction[j])||!std::isfinite(a.offset[j]))return;
            if(glm::length(a.direction)<.001F)return;
            a.position=(a.position-center)*scale+origin;
            a.offset*=scale;
            a.direction=glm::normalize(a.direction);loaded.push_back(a);
        }
        hand.reset();delta=0;arrows=std::move(loaded);version=next;minimum=lo;maximum=hi;
        if(waitingVersion!=version)waitingVersion=0;
    }
    glm::vec3 point(const Arrow& a,const glm::mat4& model,float scale,float offset) const {
        return glm::vec3(model*glm::vec4(a.position+a.direction*(float(delta)*.334F*scale+offset),1));
    }
    float arrowLength(const glm::mat4& model,float scale) const {
        return std::max(1.8F*scale,.04F/glm::length(glm::vec3(model[0])));
    }
    template<class Commit> void input(const std::array<HandPose,2>& hands,
        const std::array<bool,2>& clicked,const std::array<bool,2>& pressed,
        std::array<bool,2>& blocked,const glm::mat4& model,float scale,bool enabled,Commit commit) {
        nearby=false;
        if(hand) {
            const auto h=*hand;blocked[h]=true;
            if(!enabled || !hands[h].valid || model!=startModel) {hand.reset();delta=0;return;}
            const auto local=glm::vec3(glm::inverse(startModel)*glm::vec4(hands[h].position,1));
            delta=std::clamp(int(std::round(glm::dot(local-start,arrows[grabbed].direction)/(.334F*scale))),minimum,maximum);
            if(!pressed[h]) {
                hand.reset();
                if(delta) {committedVersion=version;committedDelta=delta;waitingVersion=version;++sequence;commit();}
                delta=0;
            }
            return;
        }
        if(!enabled || waitingVersion)return;
        float best=.035F;size_t bestHand=0,bestArrow=0;bool found=false;
        for(size_t h=0;h<2;++h)if(hands[h].valid && !blocked[h])for(size_t i=0;i<arrows.size();++i) {
            const auto a=point(arrows[i],model,scale,0),b=point(arrows[i],model,scale,arrowLength(model,scale));
            const auto ab=b-a;
            const float t=glm::clamp(glm::dot(hands[h].position-a,ab)/glm::dot(ab,ab),0.0F,1.0F);
            const float distance=glm::distance(hands[h].position,a+t*ab);
            if(distance<best) {best=distance;bestHand=h;bestArrow=i;found=true;}
        }
        nearby=found;
        if(found && clicked[bestHand]) {
            hand=bestHand;grabbed=bestArrow;startModel=model;
            start=glm::vec3(glm::inverse(model)*glm::vec4(hands[bestHand].position,1));
            blocked[bestHand]=true;
        }
    }
    template<class Line> void draw(const glm::mat4& model,float scale,Line line) const {
        for(const auto& a:arrows) {
            const float length=arrowLength(model,scale);
            const auto p=point(a,model,scale,0),tip=point(a,model,scale,length);
            const auto axis=glm::normalize(tip-p);
            auto side=glm::cross(axis,glm::vec3(0,1,0));
            if(glm::length(side)<.01F)side=glm::cross(axis,glm::vec3(1,0,0));
            side=glm::normalize(side)*glm::distance(p,tip)*.2F;
            const auto back=tip-(tip-p)*.35F;
            const glm::vec3 color=delta<0?glm::vec3(1,.3F,.1F):(hand||nearby)?glm::vec3(1,1,.1F):glm::vec3(0,.9F,1);
            // A small spatial shaft survives mirror downsampling and remains
            // identifiable when viewed from either side of the helix.
            const auto cross=glm::normalize(glm::cross(axis,side))*glm::length(side);
            line(p,tip,color);
            for(const auto& radial:std::array<glm::vec3,4>{side,-side,cross,-cross}) {
                line(p+radial*.18F,back+radial*.18F,color);
                line(tip,back+radial,color);
            }
        }
    }
};
}
