#pragma once
#include "interaction.hpp"
#include "menu_layout.hpp"

namespace nadoc_vr {
struct RemotePanelTarget {
    MenuPlacement* placement;
    MenuPanelBounds border;
    MenuPanelBounds surface;
    float width=.025F;
};
// One gesture owns one panel. The nearest whole surface occludes borders behind it.
class RemotePanelControl {
 public:
    MenuPlacement* active=nullptr;
    size_t hand=0;
    bool resizing=false;
    std::array<std::optional<glm::vec3>,2> rayPoints;
    static float outsideMargin(const RemotePanelTarget& t) {return std::max(t.width,.05F/t.placement->scale());}
    void cancel() {
        if(active)active->endRemote();
        active=nullptr;last=nullptr;rayPoints={};
    }
    std::array<bool,2> update(const std::vector<RemotePanelTarget>& targets,
            const std::array<HandPose,2>& hands,const std::array<bool,2>& clicked,
            const std::array<bool,2>& held,glm::vec3 head,double now) {
        std::array<bool,2> blocked{};rayPoints={};
        for(const auto& t:targets)t.placement->remoteHovered=false;
        if(active) {
            blocked[hand]=true; // Consume release, too: never click through.
            const bool present=std::any_of(targets.begin(),targets.end(),[&](auto t){return t.placement==active;});
            if(!present || !hands[hand].valid || !held[hand]) {
                const bool tap=present && hands[hand].valid && !resizing && now-started<.35 && glm::distance(active->position(),initialPosition)<std::max(.035F,radius*.025F);
                auto* released=active;active->endRemote();active=nullptr;
                last=tap?released:nullptr;lastHand=hand;releasedAt=now;
            } else {
                const auto& h=hands[hand];const auto dir=h.orientation*glm::vec3(0,0,-1);
                if(resizing) {
                    const auto normal=initialOrientation*glm::vec3(0,0,1);
                    const float denominator=glm::dot(dir,normal);
                    if(std::abs(denominator)>1e-5F) {
                        const float t=glm::dot(initialPosition-h.position,normal)/denominator;
                        if(t>0) {
                            const auto local=glm::inverse(initialOrientation)*(h.position+dir*t-initialPosition);
                            active->remoteTransform(initialPosition,initialOrientation,
                                initialScale*glm::length(glm::vec2(local))/initialExtent,2);
                        }
                    }
                } else {
                    const auto offset=h.position-head;
                    const float b=glm::dot(offset,dir),discriminant=b*b-glm::dot(offset,offset)+radius*radius;
                    if(discriminant>=0) {
                        const float t=-b+std::sqrt(discriminant);
                        if(t>0) {
                            const auto direction=glm::normalize(h.position+dir*t-head);
                            const auto rotation=glm::rotation(initialDirection,direction);
                            active->remoteTransform(head+rotation*relativeCenter,rotation*initialOrientation,initialScale,1);
                        }
                    }
                }
                rayPoints[hand]=active->worldPoint(grabLocal);
                return blocked;
            }
        }
        for(size_t h=0;h<2;++h)if(!blocked[h]) {
            const RemotePanelTarget* nearest=nullptr;glm::vec3 local{};float distance=30,nearestEdge=1e9F;bool nearestInside=false;
            for(const auto& t:targets) {
                // A small outside margin makes thin rails usable with hand tremor
                // without extending their inside edge into buttons or desktop pixels.
                const glm::vec2 halo(outsideMargin(t));
                if(auto p=t.placement->rayPanelLocalPoint(hands[h],t.surface.minimum-halo,t.surface.maximum+halo,30)) {
                    const float d=glm::distance(hands[h].position,t.placement->worldPoint(*p));
                    const bool inside=p->x>=t.surface.minimum.x && p->x<=t.surface.maximum.x && p->y>=t.surface.minimum.y && p->y<=t.surface.maximum.y;
                    const auto b=t.border;
                    const float edge=std::min({std::abs(p->x-b.minimum.x),std::abs(p->x-b.maximum.x),
                        std::abs(p->y-b.minimum.y),std::abs(p->y-b.maximum.y)})*t.placement->scale();
                    if(d<distance-1e-4F || (std::abs(d-distance)<=1e-4F &&
                            ((inside && !nearestInside) || (inside==nearestInside && edge<nearestEdge)))) {
                        nearest=&t;local=*p;distance=d;nearestInside=inside;nearestEdge=edge;
                    }
                }
            }
            if(!nearest)continue;
            const auto b=nearest->border;
            const float halo=outsideMargin(*nearest);
            const bool inside=local.x>=b.minimum.x-halo && local.x<=b.maximum.x+halo && local.y>=b.minimum.y-halo && local.y<=b.maximum.y+halo;
            const float edge=std::min({local.x-b.minimum.x,b.maximum.x-local.x,local.y-b.minimum.y,b.maximum.y-local.y});
            if(!inside || edge>nearest->width)continue;
            // Chrome outside the frame (notably desktop Close) owns its area.
            if(edge<0 && nearestInside)continue;
            blocked[h]=true;nearest->placement->remoteHovered=true;
            rayPoints[h]=nearest->placement->worldPoint(local);
            if(!clicked[h] || active || nearest->placement->dragHand() || nearest->placement->resizeActive())continue;
            active=nearest->placement;hand=h;started=now;
            resizing=last==active && lastHand==h && now-releasedAt<=.35;
            last=nullptr;initialPosition=active->position();initialOrientation=active->orientation();initialScale=active->scale();
            grabLocal=local;
            const auto grab=active->worldPoint(local);
            relativeCenter=initialPosition-head;radius=glm::distance(grab,head);
            initialDirection=glm::normalize(grab-head);
            initialExtent=std::max(.01F,glm::length(glm::vec2(local))*initialScale);
            active->remoteTransform(initialPosition,initialOrientation,initialScale,resizing?2:1);
            return blocked;
        }
        return blocked;
    }
 private:
    MenuPlacement* last=nullptr;
    size_t lastHand=0;
    double releasedAt=-1,started=0;
    glm::vec3 initialPosition{},relativeCenter{},initialDirection{},grabLocal{};
    glm::quat initialOrientation{1,0,0,0};
    float initialScale=1,initialExtent=1,radius=1;
};
}
