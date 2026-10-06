#pragma once
#include "interaction.hpp"
#include "menu_layout.hpp"

namespace nadoc_vr {
// Desktop pixels occupy only content(); title, Close and grip frame lie outside.
struct DesktopPanel {
    bool open=false;
    bool magnifying=false;
    glm::vec2 pointer{.5F,.5F};
    bool closeHovered=false;
    MenuPlacement placement;
    float aspect=16.F/9.F;
    MenuPanelBounds content() const { return {{-.9F,-.9F/aspect},{.9F,.9F/aspect}}; }
    MenuPanelBounds bounds() const {
        const auto b=content();return {{b.minimum.x-.035F,b.minimum.y-.035F},{b.maximum.x+.035F,b.maximum.y+.035F}};
    }
    MenuPanelBounds closeBounds() const {
        const auto b=bounds();return {{b.maximum.x-.265F,b.maximum.y+.025F},{b.maximum.x-.035F,b.maximum.y+.095F}};
    }
    MenuPanelBounds chromeBounds() const {
        const auto b=bounds();return {b.minimum,{b.maximum.x,closeBounds().maximum.y+.02F}};
    }
    void show(const glm::vec3& controller,const glm::quat& orientation) {
        open=true;magnifying=false;closeHovered=false;
        placement.openFromController({true,false,controller,orientation},1.35F);
    }
    std::optional<glm::vec3> hit(const HandPose& hand) const {
        if(!open)return std::nullopt;
        const auto b=chromeBounds();return placement.rayPanelLocalPoint(hand,b.minimum,b.maximum);
    }
    static bool contains(MenuPanelBounds b,glm::vec3 p) {
        return p.x>=b.minimum.x && p.x<=b.maximum.x && p.y>=b.minimum.y && p.y<=b.maximum.y;
    }
    std::optional<glm::vec2> uv(const HandPose& hand) const {
        const auto p=hit(hand);const auto b=content();
        if(!p || !contains(b,*p))return std::nullopt;
        return glm::vec2((p->x-b.minimum.x)/(b.maximum.x-b.minimum.x),
                         (b.maximum.y-p->y)/(b.maximum.y-b.minimum.y));
    }
    template<class Feedback> void grips(const std::array<HandPose,2>& hands,
            const std::array<bool,2>& clicked,std::array<bool,2>& blocked,Feedback feedback) {
        if(!open)return;
        const auto b=bounds();placement.update(hands,.935F);
        if(!blocked[0] && !blocked[1] && (clicked[0]||clicked[1]) &&
                placement.beginBorderResize(hands,b.minimum,b.maximum)) {
            feedback(0,.52F);feedback(1,.52F);
        }
        if(!placement.resizeActive() && !placement.dragHand())for(size_t h=0;h<2;++h)
            if(!blocked[h] && clicked[h] && placement.beginDrag(h,hands,b.minimum,b.maximum)) {
                feedback(h,.48F);break;
            }
        placement.update(hands,.935F);
        if(placement.resizeActive())blocked.fill(true);
        if(placement.dragHand())blocked[*placement.dragHand()]=true;
    }
};
}
