#pragma once
#include "interaction.hpp"
#include "stroke_font.hpp"
#include <ostream>

namespace nadoc_vr {
struct SelectionWheelSpec {
    static constexpr size_t hand=0;
    static constexpr float phase=0, winding=1;
    static constexpr std::array<const char*,6> levels{"default","cluster","strand","domain","xover","base"};
    static constexpr std::array<const char*,6> labels{"DRILL","CLUSTER","STRAND","DOMAIN","CROSSOVER","BASES"};
};
struct EditWheelSpec {
    static constexpr size_t hand=1;
    // Preserve the established compass: Ligate right, Nick up, Undo left, Redo down.
    static constexpr float phase=glm::half_pi<float>(), winding=-1;
    static constexpr std::array<const char*,4> levels{"ligate","nick","undo","redo"};
    static constexpr std::array<const char*,4> labels{"LIGATE","NICK","UNDO","REDO"};
};
// Both controllers use the same thumb-driven gesture and drawing implementation.
template<class Spec> class TouchpadWheel {
 public:
    static constexpr auto levels=Spec::levels, labels=Spec::labels;
    static constexpr size_t count=levels.size();
    static float angle(size_t i) {return Spec::phase+Spec::winding*float(i)*glm::two_pi<float>()/float(count);}
    static constexpr float deadzone=.30F, outer=.175F, inner=.040F, labelRadius=.115F;
    struct Result { std::optional<size_t> commit; bool hoverChanged=false; };
    static glm::vec2 direction(size_t i) {
        const float a=angle(i);
        return {std::sin(a),std::cos(a)};
    }
    static std::optional<size_t> sector(glm::vec2 axis) {
        if(!std::isfinite(axis.x)||!std::isfinite(axis.y)||glm::length(axis)<deadzone)return {};
        float a=Spec::winding*(std::atan2(axis.x,axis.y)-Spec::phase)+glm::pi<float>()/float(count);
        a=std::fmod(a+glm::two_pi<float>()*2,glm::two_pi<float>());
        return size_t(std::floor(a/(glm::two_pi<float>()/float(count))))%count;
    }
    // Tool workflows replace the edit compass with left/right navigation.
    void setWorkflow(bool active,bool confirm=false) {
        if(workflow_!=active)cancel();
        workflow_=active;confirm_=confirm;
    }
    void setSweep(bool active) {if(sweep_!=active)cancel();sweep_=active;}
    size_t itemCount() const {return workflow_||sweep_?2:count;}
    const char* itemLabel(size_t i) const {return sweep_?(i==0?"DELETE LAST":"ADD POINT"):workflow_?(i==0?"BACK":confirm_?"CONFIRM":"NEXT"):labels[i];}
    float itemAngle(size_t i) const {return workflow_||sweep_?(i==0?-glm::half_pi<float>():glm::half_pi<float>()):angle(i);}
    glm::vec2 itemDirection(size_t i) const {const float a=itemAngle(i);return {std::sin(a),std::cos(a)};}
    std::optional<size_t> itemSector(glm::vec2 axis) const {
        if(!workflow_&&!sweep_)return sector(axis);
        if(!std::isfinite(axis.x)||!std::isfinite(axis.y)||glm::length(axis)<deadzone)return {};
        return axis.x<0?0:1;
    }
    Result update(bool pressed,glm::vec2 axis,const HandPose& hand,bool enabled=true) {
        Result result;
        consumed_=open_ || pressed || pending_.has_value();
        if(pending_) {
            wasPressed_=pressed;
            if(hand.valid) {
                position_=hand.position+hand.orientation*glm::vec3(0,.04F,-.06F);
                orientation_=MenuPlacement::controllerOrientation(hand.orientation);
            }
            return result;
        }
        if(!enabled || !hand.valid) { cancel(); wasPressed_=pressed; return result; }
        const bool clicked=pressed&&!wasPressed_;
        wasPressed_=pressed;
        if(clicked)open_=true;
        if(!open_)return result;
        position_=hand.position+hand.orientation*glm::vec3(0,.04F,-.06F);
        orientation_=MenuPlacement::controllerOrientation(hand.orientation);
        if(!pressed) {
            // OpenXR axes can reset on release. Commit the last held sample.
            result.commit=hovered_;open_=false;hovered_.reset();return result;
        }
        const auto next=itemSector(axis);
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
    // Dismissing a gesture does not dismiss an operation awaiting acknowledgement.
    void cancel() {open_=false;hovered_.reset();consumed_=false;axis_={};}
    void setPending(std::optional<size_t> item) {
        if(item==pending_)return;
        cancel();pending_=item;
        consumed_=pending_.has_value();
    }
    auto pending() const {return pending_;}
    void close() {cancel();}
    bool open() const {return open_ || pending_.has_value();}
    bool blocksInput() const {return consumed_ || pending_.has_value();}
    auto hovered() const {return hovered_;}
    glm::vec3 worldPoint(glm::vec3 p) const {return position_+orientation_*p;}
    template<class T> std::array<T,2> filter(std::array<T,2> values) const {
        if(blocksInput())values[Spec::hand]={};
        return values;
    }
    void writeJson(std::ostream& out,const std::string& selected) const {
        out<<",\"selection_wheel\":{\"open\":"<<(open_?"true":"false")
           <<",\"hovered\":"<<(hovered_?std::to_string(*hovered_):"null")<<",\"items\":[";
        for(size_t i=0;i<count;++i) {
            if(i)out<<',';
            const auto d=direction(i);const auto p=worldPoint({d.x*labelRadius,d.y*labelRadius,0});
            out<<"{\"level\":\""<<levels[i]<<"\",\"label\":\""<<labels[i]
               <<"\",\"active\":"<<(selected==levels[i]?"true":"false")
               <<",\"axis\":["<<d.x<<','<<d.y<<"],\"center\":["<<p.x<<','<<p.y<<','<<p.z<<"]}";
        }
        out<<"]}";
    }
    template<class Line> void draw(Line line,const std::string& selected,double time=0) const {
        if(!open())return;
        auto segment=[&](glm::vec2 a,glm::vec2 b,glm::vec3 color) {
            line(worldPoint({a.x,a.y,0}),worldPoint({b.x,b.y,0}),color);
        };
        for(size_t item=0;item<itemCount();++item) {
            if(pending_ && pending_!=item)continue;
            const bool hover=pending_==item || hovered_==item;
            const glm::vec3 color=hover?glm::vec3(1,.78F,.20F):(!workflow_ && !sweep_ && selected==levels[item])?glm::vec3(.4F,1,.62F):glm::vec3(.3F,.7F,.96F);
            const float center=itemAngle(item);
            auto polar=[](float a,float r){return glm::vec2(std::sin(a),std::cos(a))*r;};
            const float lo=center-glm::pi<float>()/float(itemCount())+.025F,hi=center+glm::pi<float>()/float(itemCount())-.025F;
            for(float r:{inner,outer})for(int j=0;j<16;++j)
                segment(polar(glm::mix(lo,hi,float(j)/16),r),polar(glm::mix(lo,hi,float(j+1)/16),r),color);
            for(float a:{lo,hi})segment(polar(a,inner),polar(a,outer),color);
            if(hover)for(float r=outer-.018F;r<outer;r+=.003F)for(int j=0;j<16;++j)
                segment(polar(glm::mix(lo,hi,float(j)/16),r),polar(glm::mix(lo,hi,float(j+1)/16),r),color);
            const std::string label=itemLabel(item);const float scale=.00165F;
            const auto p=itemDirection(item)*labelRadius;
            if(pending_) {
                const auto spinner=p+glm::vec2(0,.026F);
                for(int j=0;j<24;++j) {
                    const float a=float(time*5)+float(j)*glm::two_pi<float>()/32;
                    const float b=a+glm::two_pi<float>()/32;
                    segment(spinner+polar(a,.011F),spinner+polar(b,.011F),color);
                }
            }
            for(size_t c=0;c<label.size();++c) {
                const auto rows=glyph(label[c]);
                for(size_t row=0;row<rows.size();++row)for(int col=0;col<5;++col)if(rows[row]&(1U<<(4-col))) {
                    const glm::vec2 q{p.x+(float(c*6+col)-float(label.size()*6)/2)*scale,p.y+(.5F*7-float(row))*scale};
                    segment(q,q+glm::vec2(scale*.85F,0),color);
                }
            }
        }
        if(pending_)return;
        const auto p=axis_*(outer-.025F);
        segment({0,0},p,{1,.9F,.7F});
        segment(p-glm::vec2(.004F,0),p+glm::vec2(.004F,0),{1,1,1});
        segment(p-glm::vec2(0,.004F),p+glm::vec2(0,.004F),{1,1,1});
    }
 private:
    bool workflow_=false,confirm_=false,sweep_=false;
    bool open_=false,wasPressed_=false,consumed_=false;
    std::optional<size_t> hovered_,pending_;
    glm::vec2 axis_{};
    glm::vec3 position_{};
    glm::quat orientation_{1,0,0,0};
};
using SelectionWheel=TouchpadWheel<SelectionWheelSpec>;
using EditWheel=TouchpadWheel<EditWheelSpec>;
}
