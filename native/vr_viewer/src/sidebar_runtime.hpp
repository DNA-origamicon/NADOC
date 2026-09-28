#pragma once
#include "sidebar_grips.hpp"
// Included after the native GL surface types; owns both sidebar panels.
class SidebarRuntime {
 public:
    std::array<nadoc_vr::SidebarMenu,2> menus{nadoc_vr::SidebarMenu(0),nadoc_vr::SidebarMenu(1)};
    std::array<MenuPanelSurface,2> surfaces;
    void initialize() { for(auto& s:surfaces) s.initialize(); }
    void shutdown() { for(auto& s:surfaces) s.shutdown(); }
    bool anyOpen() const {return menus[0].open||menus[1].open;}
    void toggle(size_t hand,const glm::vec3& head,const glm::quat& orientation) {
        auto& m=menus.at(hand); m.open=!m.open; m.hovered.clear(); m.focus.reset(); m.pressed.clear();
        if(m.open) {
            // Independent world-docked columns, centered below the tracked eye.
            // Border grip/resize and Dock/Follow retain the existing tablet contract.
            m.placement.openDocked(head+orientation*glm::vec3(hand==0?-.34F:.34F,-.13F,-.95F),orientation);
            while(m.placement.scale()>.651F) if(!m.placement.adjustScale(-1)) break;
        }
    }
    template<class Feedback> std::array<bool,2> grips(const std::array<nadoc_vr::HandPose,2>& hands,
            const std::array<bool,2>& clicked,Feedback feedback) {
        return nadoc_vr::updateSidebarGrips(menus,hands,clicked,feedback);
    }
    bool trackpad(size_t hand, glm::vec2 axis, const nadoc_vr::HandPose& pose) {
        auto& m=menus[hand];
        if(!m.open) return false;
        std::string rayId;
        float nearest=1e9F;
        for(const auto& candidate:menus) if(candidate.open) {
            auto point=candidate.placement.rayPanelLocalPoint(pose,candidate.bounds().minimum,candidate.bounds().maximum);
            if(!point) continue;
            const float distance=glm::length(candidate.placement.worldPoint(*point)-pose.position);
            if(distance>=nearest) continue;
            nearest=distance;
            const auto control=candidate.hit(pose);
            rayId=control?(candidate.hand==m.hand?control->id:std::to_string(candidate.hand)+":"+control->id):"";
        }
        const bool center=glm::length(axis)<.45F;
        if(!m.focus.active) {
            m.focus.begin(m.customTab?m.controls().front().id:"tab:"+m.tab().key,rayId);
            return true;
        }
        if(center) {m.focus.reset();return true;}
        m.navigate(axis);
        m.focus.begin(m.focus.id,rayId);
        return true;
    }
    template<class Action> void activate(nadoc_vr::SidebarMenu& menu,
            const nadoc_vr::SidebarControl& control,size_t hand,
            const std::array<nadoc_vr::HandPose,2>& hands,double now,Action action) {
        if(control.enabled) {
            menu.pressed=control.id;menu.pressedUntil=now+nadoc_vr::ui_style::pressSeconds;
            action("feedback:activate",hand);
        }
        const auto next=menu.activate(control);
        if(next=="dock") menu.placement.toggleDock(static_cast<size_t>(menu.hand),hands,.515F);
        else if(!next.empty()) action(next,static_cast<size_t>(menu.hand));
        if(!menu.open) menu.focus.reset();
    }
    template<class Action> std::array<bool,2> input(const std::array<nadoc_vr::HandPose,2>& hands,
            const std::array<bool,2>& clicked,const std::array<bool,2>& held,std::array<bool,2> blocked,const std::array<float,2>& foreground,double now,Action action) {
        for(auto& m:menus) {m.hovered.clear();if(now>=m.pressedUntil)m.pressed.clear();if(!m.open)m.focus.reset();}
        for(size_t h=0;h<2;++h) if(!blocked[h]) {
            // Resolve the nearest physical panel, including its blank/disabled areas.
            nadoc_vr::SidebarMenu* target=nullptr; float distance=foreground[h];
            for(auto& m:menus) if(m.open) {
                const auto b=m.bounds();
                auto local=m.placement.rayPanelLocalPoint(hands[h],b.minimum,b.maximum);
                if(local) {float d=glm::length(m.placement.worldPoint(*local)-hands[h].position);if(d<distance){target=&m;distance=d;}}
            }
            auto& owned=menus[h];
            if(owned.open && owned.focus.active) {
                const auto ray=target?target->hit(hands[h]):std::nullopt;
                const std::string rayId=ray?std::to_string(target->hand)+":"+ray->id:"";
                // Only this controller decides when to relinquish its navigation focus.
                owned.focus.pointer(target==&owned && ray?ray->id:rayId,now,held[h]);
                if(owned.focus.active) {
                    blocked[h]=true;
                    for(const auto& c:owned.controls()) if(c.id==owned.focus.id && clicked[h]) {
                        activate(owned,c,h,hands,now,action);break;
                    }
                    continue;
                }
            }
            if(!target) continue;
            blocked[h]=true;
            if(target->focus.active) continue;
            auto c=target->hit(hands[h]);
            if(!c) continue;
            target->hovered=c->id;
            if(c->id=="scrollbar" && c->enabled && held[h]) {
                auto point=target->placement.rayPanelLocalPoint(hands[h],target->bounds().minimum,target->bounds().maximum);
                if(point) target->scrollTo(point->y);
            } else if(clicked[h]) {
                activate(*target,*c,h,hands,now,action);
            }
        }
        return blocked;
    }
    bool scrollAt(const nadoc_vr::HandPose& hand,int direction=0) {
        nadoc_vr::SidebarMenu* target=nullptr;float distance=1e9F;
        for(auto& m:menus) if(m.open) {
            const auto b=m.bounds();
            auto p=m.placement.rayPanelLocalPoint(hand,b.minimum,b.maximum);
            if(p) {float d=glm::length(m.placement.worldPoint(*p)-hand.position);if(d<distance){target=&m;distance=d;}}
        }
        if(target&&direction) target->scroll(direction);
        return target!=nullptr;
    }
    static std::string label(const nadoc_vr::SidebarMenu& m,const nadoc_vr::SidebarControl& c) {
        return std::string(m.hand==0?"LEFT / ":"RIGHT / ")+c.label+" ["+c.id+"]";
    }
    std::string hoverLabel() const {
        for(const auto& m:menus) if(m.open&&!m.hovered.empty()) {
            int index=0;
            for(const auto& c:m.controls()) {
                if(c.id==m.hovered) return nadoc_vr::scrywrite::witnessHoverLabel(entries(),10000+m.hand*1000+index);
                ++index;
            }
        }
        return {};
    }
    std::vector<nadoc_vr::scrywrite::WitnessMenuEntry> entries() const {
        std::vector<nadoc_vr::scrywrite::WitnessMenuEntry> out;
        for(const auto& m:menus) if(m.open) {
            int index=0;
            for(const auto& c:m.controls()) {
                auto center=(c.bounds.minimum+c.bounds.maximum)*.5F;
                auto half=(c.bounds.maximum-c.bounds.minimum)*.5F;
                auto position=m.placement.worldPoint(glm::vec3(center,0));
                out.push_back({label(m,c),10000+m.hand*1000+index++,position,
                    m.placement.orientation()*glm::vec3(half.x*m.placement.scale(),0,0),
                    m.placement.orientation()*glm::vec3(0,half.y*m.placement.scale(),0),
                    c.id,m.hand==0?"left":"right",m.tab().key,c.enabled,c.active});
            }
        }
        return out;
    }
    void draw() {
        for(size_t i=0;i<2;++i) if(menus[i].open) {
            std::vector<Vertex> lines,triangles;
            auto line=[&](glm::vec3 a,glm::vec3 b,glm::vec3 color){lines.push_back({a,color,1});lines.push_back({b,color,1});};
            auto fill=[&](nadoc_vr::MenuPanelBounds b,glm::vec3 color){
                for(auto p:std::array<glm::vec2,6>{b.minimum,{b.maximum.x,b.minimum.y},b.maximum,b.minimum,b.maximum,{b.minimum.x,b.maximum.y}})
                    triangles.push_back({glm::vec3(p,0),color,1});
            };
            menus[i].draw(line,fill);
            surfaces[i].update(lines,menus[i].bounds(),false,triangles);
        }
    }
    void render(const glm::mat4& projection) {
        for(size_t i=0;i<2;++i) if(menus[i].open) surfaces[i].render(projection,menus[i].placement,menus[i].bounds(),.002F);
    }
    std::string json() const {
        auto q=[](const std::string& v){return "\""+nadoc_vr::scrywrite::visualJson(v)+"\"";};
        std::ostringstream out;out<<'[';
        for(size_t i=0;i<2;++i) {
            if(i)out<<',';
            const auto& m=menus[i];
            out<<"{\"hand\":"<<i<<",\"open\":"<<(m.open?"true":"false")<<",\"tab\":"<<q(m.tab().key)
                <<",\"offset\":"<<m.offset()<<",\"total\":"<<m.total()<<",\"hover_id\":"<<q(m.hovered)
                <<",\"input_mode\":"<<q(m.focus.active?"trackpad":"pointer")<<",\"focus_id\":"<<q(m.focus.id)
                <<",\"grip_state\":"<<q(nadoc_vr::gripFrameName(m.gripState))
                <<",\"grip_nearby\":["<<(m.gripNearby[0]?"true":"false")<<','<<(m.gripNearby[1]?"true":"false")<<']'
                <<",\"scale\":"<<m.placement.scale()<<",\"position\":["<<m.placement.position().x<<','<<m.placement.position().y<<','<<m.placement.position().z<<']'
                <<",\"grip_targets\":[";
            for(int edge=0;edge<4;++edge) {
                if(edge)out<<',';
                const auto b=m.bounds();
                glm::vec3 local((b.minimum+b.maximum)*.5F,0);
                if(edge<2)local.x=edge==0?b.minimum.x:b.maximum.x;
                else local.y=edge==2?b.maximum.y:b.minimum.y;
                const auto point=m.placement.worldPoint(local);
                out<<'['<<point.x<<','<<point.y<<','<<point.z<<']';
            }
            out<<"],\"collapsed_sections\":[";
            bool first=true;
            for(const auto& row:m.tab().rows) if(m.collapsed.contains(row.id)) {
                if(!first) out<<',';
                out<<q(row.id);first=false;
            }
            out<<']'
                <<",\"layout\":"<<q(m.audit.status())<<",\"layout_detail\":"<<q(m.audit.summary())<<'}';
        }
        out<<']';return out.str();
    }
};
