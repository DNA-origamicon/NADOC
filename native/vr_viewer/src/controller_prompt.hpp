#pragma once
#include "interaction.hpp"
#include <deque>
#include <functional>
#include <stdexcept>
#include <string>
#include <vector>

namespace nadoc_vr {
// Small modal desktop dialogs map to this asynchronous, controller-docked asset.
// No default action: every answer requires a fresh directional press/release.
class ControllerPrompt {
 public:
    struct Option { std::string id, label; };
    struct Request {
        std::string title, message;
        std::vector<Option> options{{"ok","OK"}};
        std::function<void(const std::string&)> complete{};
        std::string key{}; // Optional owner key for withdrawing stale browser decisions.
    };
    void show(Request request) {
        if(request.options.empty() || request.options.size()>4)
            throw std::invalid_argument("Controller prompts require 1 to 4 options");
        for(size_t i=0;i<request.options.size();++i) {
            const auto& o=request.options[i];
            if(o.id.empty() || o.label.empty())throw std::invalid_argument("Prompt options need IDs and labels");
            for(size_t j=0;j<i;++j)if(o.id==request.options[j].id)
                throw std::invalid_argument("Prompt option IDs must be unique");
        }
        queue_.push_back(std::move(request));
        if(queue_.size()==1)reset();
    }
    void withdraw(const std::string& key) {
        const bool front=active() && queue_.front().key==key;
        std::erase_if(queue_,[&](const auto& r){return r.key==key;});
        if(front)reset();
    }
    bool active() const {return !queue_.empty();}
    size_t queued() const {return queue_.size();}
    const Request& request() const {return queue_.front();}
    auto hovered() const {return hover_;}
    size_t page() const {return page_;}
    void suspend() {armed_=false;pressed_=false;hover_.reset();visible_=false;}
    static glm::vec2 direction(size_t i,size_t count) {
        const float a=count==2?(i==0?-glm::half_pi<float>():glm::half_pi<float>()):float(i)*glm::two_pi<float>()/float(count);
        return {std::sin(a),std::cos(a)};
    }
    std::optional<size_t> sector(glm::vec2 axis) const {
        if(!active() || !std::isfinite(axis.x) || !std::isfinite(axis.y) || glm::length(axis)<.30F)return {};
        size_t best=0;float dot=-2;
        for(size_t i=0;i<request().options.size();++i) {
            const float d=glm::dot(glm::normalize(axis),direction(i,request().options.size()));
            if(d>dot){dot=d;best=i;}
        }
        return best;
    }
    template<class Pulse> void update(bool pressed,glm::vec2 axis,const HandPose& hand,double now,Pulse pulse) {
        if(!active())return;
        if(!hand.valid){suspend();return;}
        visible_=true;position_=hand.position+hand.orientation*glm::vec3(0,.04F,-.06F);
        orientation_=MenuPlacement::controllerOrientation(hand.orientation);
        // Space pulses by actual delivery time; stalled frames never collapse them.
        if(pulses_<3 && now>=nextPulse_) {pulse(.55F);++pulses_;nextPulse_=now+.16;}
        if(!armed_) {if(!pressed)armed_=true;return;}
        if(pressed)hover_=sector(axis);
        if(!pressed && pressed_ && hover_ && pulses_==3) {
            auto done=std::move(queue_.front());const auto id=done.options[*hover_].id;
            queue_.pop_front();reset();
            if(done.complete)done.complete(id);
            return;
        }
        if(!pressed && pressed_ && !hover_ && pages()>1)page_=(page_+1)%pages();
        pressed_=pressed;
        if(!pressed)hover_.reset();
    }
    glm::vec3 worldPoint(glm::vec3 p) const {return position_+orientation_*p;}
    // UI is the viewer's SolidUi asset (also usable by its desktop evaluator).
    template<class Ui> void draw(Ui& ui) const {
        ui.vertices.clear();if(!active() || !visible_)return;
        const auto lines=wrap(request().message,46);
        const auto titles=wrap(request().title,46);
        const float scale=.0017F, lineHeight=.018F;
        const size_t first=page_*8,last=std::min(first+8,lines.size());
        const float bottom=.19F, top=bottom+.10F+float(last-first+titles.size()-1)*lineHeight;
        ui.raisedSlate(-.25F,bottom,.5F,top-bottom,.009F,{.025F,.045F,.07F},{.3F,.7F,.96F});
        float y=top-.025F;
        for(const auto& title:titles) {
            ui.text(title,-.235F,y,scale,{.4F,.8F,1},.012F);y-=lineHeight;
        }
        y-=.007F;
        for(size_t i=first;i<last;++i){ui.text(lines[i],-.235F,y,scale,{.95F,.97F,1},.012F);y-=lineHeight;}
        ui.text("PRESS, SLIDE, RELEASE TO CHOOSE",-.235F,bottom+.026F,.0014F,{.55F,.75F,.9F},.012F);
        if(pages()>1)ui.text("CENTER CLICK: PAGE "+std::to_string(page_+1)+"/"+std::to_string(pages()),
            -.235F,bottom+.01F,.0014F,{.55F,.75F,.9F},.012F);
        const size_t count=request().options.size();
        for(size_t i=0;i<count;++i) {
            const auto color=hover_==i?glm::vec3(1,.75F,.18F):glm::vec3(.12F,.28F,.4F);
            const auto dir=direction(i,count);const float center=std::atan2(dir.x,dir.y);
            const float half=glm::pi<float>()/float(count)-.035F;
            auto p=[](float a,float r){return glm::vec3(std::sin(a)*r,std::cos(a)*r,.01F);};
            for(int j=0;j<40;++j) {
                const float a=center-half+2*half*j/40,b=center-half+2*half*(j+1)/40;
                ui.triangle(p(a,.04F),p(a,.175F),p(b,.175F),color);
                ui.triangle(p(a,.04F),p(b,.175F),p(b,.04F),color);
            }
            const auto labels=wrap(request().options[i].label,12);
            float ly=dir.y*.11F+float(labels.size()-1)*.007F;
            for(const auto& label:labels) {
                ui.text(label,dir.x*.11F-float(label.size())*.0042F,ly,.0014F,{1,1,1},.012F);ly-=.014F;
            }
        }
        for(auto& v:ui.vertices)v.position=worldPoint(v.position);
    }
 private:
    static std::vector<std::string> wrap(const std::string& text,size_t width) {
        std::vector<std::string> lines;std::string line;
        for(char c:text) {
            if(c=='\n'){lines.push_back(line);line.clear();continue;}
            line+=c;
            if(line.size()>=width) {
                const auto space=line.rfind(' ');
                if(space!=std::string::npos && space>0){lines.push_back(line.substr(0,space));line.erase(0,space+1);}
                else {lines.push_back(line);line.clear();}
            }
        }
        if(!line.empty() || lines.empty())lines.push_back(line);
        return lines;
    }
    size_t pages() const {return (wrap(request().message,46).size()+7)/8;}
    void reset(){suspend();pulses_=0;nextPulse_=0;page_=0;}
    size_t page_=0;
    std::deque<Request> queue_;
    bool armed_=false,pressed_=false,visible_=false;
    int pulses_=0;double nextPulse_=0;
    std::optional<size_t> hover_;
    glm::vec3 position_{};glm::quat orientation_{1,0,0,0};
};
}
