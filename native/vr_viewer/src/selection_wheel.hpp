#pragma once
#include "interaction.hpp"
#include "stroke_font.hpp"
#include <ostream>

namespace nadoc_vr {
// Thumb coordinates, not controller position, choose a sector. Clockwise from up.
class SelectionWheel {
 public:
    static constexpr std::array<const char*,6> levels{"default","cluster","strand","domain","xover","base"};
    static constexpr std::array<const char*,6> labels{"DRILL","CLUSTER","STRAND","DOMAIN","CROSSOVER","BASES"};
    static constexpr float deadzone=.30F, outer=.175F, inner=.040F, labelRadius=.115F;
    struct Result { std::optional<size_t> commit; bool hoverChanged=false; };
    static glm::vec2 direction(size_t i) {
        const float a=float(i)*glm::two_pi<float>()/6.F;
        return {std::sin(a),std::cos(a)};
    }
    static std::optional<size_t> sector(glm::vec2 axis) {
        if(!std::isfinite(axis.x)||!std::isfinite(axis.y)||glm::length(axis)<deadzone)return {};
        float angle=std::atan2(axis.x,axis.y)+glm::pi<float>()/6.F;
        if(angle<0)angle+=glm::two_pi<float>();
        return size_t(std::floor(angle/(glm::two_pi<float>()/6.F)))%6;
    }
    Result update(bool pressed,glm::vec2 axis,const HandPose& hand,bool enabled=true) {
        Result result;
        consumed_=open_ || pressed;
        if(!enabled || !hand.valid) { cancel(); wasPressed_=pressed; return result; }
        const bool clicked=pressed&&!wasPressed_;
        wasPressed_=pressed;
        if(clicked)open_=true;
        if(!open_)return result;
        position_=hand.position+hand.orientation*glm::vec3(0,.04F,-.06F);
        orientation_=glm::normalize(hand.orientation*glm::angleAxis(-glm::quarter_pi<float>(),glm::vec3(1,0,0)));
        if(!pressed) {
            // OpenXR axes can reset on release. Commit the last held sample.
            result.commit=hovered_;open_=false;hovered_.reset();return result;
        }
        const auto next=sector(axis);
        result.hoverChanged=next && next!=hovered_;
        hovered_=next;
        axis_=next?glm::normalize(axis)*std::min(glm::length(axis),1.F):glm::vec2(0);
        return result;
    }
    template<class Select,class Pulse>
    void input(bool pressed,glm::vec2 axis,const HandPose& hand,bool enabled,Select select,Pulse pulse) {
        const auto result=update(pressed,axis,hand,enabled);
        if(result.hoverChanged)pulse(.14F);
        if(result.commit) {select(levels[*result.commit]);pulse(.32F);}
    }
    void cancel() {open_=false;hovered_.reset();consumed_=false;axis_={};}
    bool open() const {return open_;}
    bool blocksInput() const {return consumed_;}
    auto hovered() const {return hovered_;}
    glm::vec3 worldPoint(glm::vec3 p) const {return position_+orientation_*p;}
    template<class T> std::array<T,2> filter(std::array<T,2> values) const {
        if(consumed_)values[0]={};
        return values;
    }
    void writeJson(std::ostream& out,const std::string& selected) const {
        out<<",\"selection_wheel\":{\"open\":"<<(open_?"true":"false")
           <<",\"hovered\":"<<(hovered_?std::to_string(*hovered_):"null")<<",\"items\":[";
        for(size_t i=0;i<6;++i) {
            if(i)out<<',';
            const auto d=direction(i);const auto p=worldPoint({d.x*labelRadius,d.y*labelRadius,0});
            out<<"{\"level\":\""<<levels[i]<<"\",\"label\":\""<<labels[i]
               <<"\",\"active\":"<<(selected==levels[i]?"true":"false")
               <<",\"axis\":["<<d.x<<','<<d.y<<"],\"center\":["<<p.x<<','<<p.y<<','<<p.z<<"]}";
        }
        out<<"]}";
    }
    template<class Line> void draw(Line line,const std::string& selected) const {
        if(!open_)return;
        auto segment=[&](glm::vec2 a,glm::vec2 b,glm::vec3 color) {
            line(worldPoint({a.x,a.y,0}),worldPoint({b.x,b.y,0}),color);
        };
        for(size_t item=0;item<6;++item) {
            const bool hover=hovered_==item;
            const glm::vec3 color=hover?glm::vec3(1,.78F,.20F):selected==levels[item]?glm::vec3(.4F,1,.62F):glm::vec3(.3F,.7F,.96F);
            const float center=float(item)*glm::two_pi<float>()/6.F;
            auto polar=[](float a,float r){return glm::vec2(std::sin(a),std::cos(a))*r;};
            const float lo=center-glm::pi<float>()/6.F+.025F,hi=center+glm::pi<float>()/6.F-.025F;
            for(float r:{inner,outer})for(int j=0;j<16;++j)
                segment(polar(glm::mix(lo,hi,float(j)/16),r),polar(glm::mix(lo,hi,float(j+1)/16),r),color);
            for(float a:{lo,hi})segment(polar(a,inner),polar(a,outer),color);
            if(hover)for(float r=outer-.018F;r<outer;r+=.003F)for(int j=0;j<16;++j)
                segment(polar(glm::mix(lo,hi,float(j)/16),r),polar(glm::mix(lo,hi,float(j+1)/16),r),color);
            const std::string label=labels[item];const float scale=.00165F;
            const auto p=direction(item)*labelRadius;
            for(size_t c=0;c<label.size();++c) {
                const auto rows=glyph(label[c]);
                for(size_t row=0;row<rows.size();++row)for(int col=0;col<5;++col)if(rows[row]&(1U<<(4-col))) {
                    const glm::vec2 q{p.x+(float(c*6+col)-float(label.size()*6)/2)*scale,p.y+(.5F*7-float(row))*scale};
                    segment(q,q+glm::vec2(scale*.85F,0),color);
                }
            }
        }
        const auto p=axis_*(outer-.025F);
        segment({0,0},p,{1,.9F,.7F});
        segment(p-glm::vec2(.004F,0),p+glm::vec2(.004F,0),{1,1,1});
        segment(p-glm::vec2(0,.004F),p+glm::vec2(0,.004F),{1,1,1});
    }
 private:
    bool open_=false,wasPressed_=false,consumed_=false;
    std::optional<size_t> hovered_;
    glm::vec2 axis_{};
    glm::vec3 position_{};
    glm::quat orientation_{1,0,0,0};
};
}
