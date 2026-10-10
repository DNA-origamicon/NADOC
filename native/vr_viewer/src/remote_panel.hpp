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
    bool owns(const MenuPlacement& placement,size_t h) const {return active==&placement && (hand==h || twoHand);}
    void cancel() {
        if(active)active->endRemote();
        active=nullptr;last=nullptr;twoHand=resizing=false;rayPoints={};
    }
    std::array<bool,2> update(const std::vector<RemotePanelTarget>& targets,
            const std::array<HandPose,2>& hands,const std::array<bool,2>& clicked,
            const std::array<bool,2>& held,glm::vec3 head,double now) {
        (void)head;
        std::array<bool,2> blocked{};rayPoints={};
        for(const auto& t:targets)t.placement->remoteHovered=false;
        if(active) {
            blocked[hand]=true; // Consume release, too: never click through.
            if(twoHand) {
                blocked[1-hand]=true;
                if(!hands[hand].valid || !held[hand] || !hands[1-hand].valid || !held[1-hand]) {
                    const size_t remaining=hands[hand].valid && held[hand]?hand:1-hand;
                    twoHand=false;resizing=false;
                    if(hands[remaining].valid && held[remaining]) {
                        hand=remaining;grabLocal=secondLocal[hand];
                        beginMove(hands[hand]);
                    }
                }
            }
            const bool present=std::any_of(targets.begin(),targets.end(),[&](auto t){return t.placement==active;});
            if(!present || !hands[hand].valid || !held[hand]) {
                const bool tap=present && hands[hand].valid && !resizing && now-started<.35 && glm::distance(active->position(),initialPosition)<std::max(.035F,grabDistance[hand]*.025F);
                auto* released=active;active->endRemote();active=nullptr;twoHand=false;
                last=tap?released:nullptr;lastHand=hand;releasedAt=now;
            } else {
                const auto& h=hands[hand];const auto dir=h.orientation*glm::vec3(0,0,-1);
                if(twoHand) {
                    std::array<glm::vec3,2> points;
                    for(size_t i=0;i<2;++i)points[i]=hands[i].position+hands[i].orientation*glm::vec3(0,0,-grabDistance[i]);
                    const auto span=points[1]-points[0];
                    if(glm::length(span)>.001F) {
                        const auto rotation=glm::rotation(glm::normalize(initialSpan),glm::normalize(span));
                        const float scale=glm::clamp(initialScale*glm::length(span)/glm::length(initialSpan),MenuPlacement::kMinimumScale,MenuPlacement::kMaximumScale);
                        active->remoteTransform((points[0]+points[1])*.5F+rotation*relativeCenter*(scale/initialScale),
                            rotation*initialOrientation,scale,2);
                    }
                    for(size_t i=0;i<2;++i)rayPoints[i]=active->worldPoint(secondLocal[i]);
                    return blocked;
                } else if(resizing) {
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
                    const auto rotation=h.orientation*glm::inverse(initialHandOrientation);
                    active->remoteTransform(h.position+rotation*relativeCenter,
                        rotation*initialOrientation,initialScale,1);
                }
                rayPoints[hand]=active->worldPoint(grabLocal);
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
            if(active && nearest->placement!=active)continue;
            if(clicked[h] && active && !resizing) {
                secondLocal[hand]=grabLocal;secondLocal[h]=local;
                grabDistance[h]=distance;
                const auto first=hands[hand].position+hands[hand].orientation*glm::vec3(0,0,-grabDistance[hand]);
                const auto second=active->worldPoint(local);
                initialSpan=h==1?second-first:first-second;
                if(glm::length(initialSpan)<.01F)continue;
                initialPosition=active->position();initialOrientation=active->orientation();initialScale=active->scale();
                relativeCenter=initialPosition-(first+second)*.5F;
                twoHand=resizing=true;last=nullptr;started=now-.35;
                active->remoteTransform(initialPosition,initialOrientation,initialScale,2);
                return blocked;
            }
            if(!clicked[h] || active || nearest->placement->dragHand() || nearest->placement->resizeActive())continue;
            active=nearest->placement;hand=h;started=now;
            resizing=last==active && lastHand==h && now-releasedAt<=.35;
            last=nullptr;initialPosition=active->position();initialOrientation=active->orientation();initialScale=active->scale();
            grabLocal=local;
            const auto grab=active->worldPoint(local);
            grabDistance[h]=glm::distance(grab,hands[h].position);
            beginMove(hands[h]);
            initialExtent=std::max(.01F,glm::length(glm::vec2(local))*initialScale);
            active->remoteTransform(initialPosition,initialOrientation,initialScale,resizing?2:1);
        }
        return blocked;
    }
 private:
    // Store the full controller-relative pose, so neither depth nor wrist angle
    // is reconstructed from the headset or from a new ray/plane intersection.
    void beginMove(const HandPose& h) {
        initialPosition=active->position();initialOrientation=active->orientation();initialScale=active->scale();
        initialHandOrientation=h.orientation;relativeCenter=initialPosition-h.position;
        grabDistance[hand]=glm::distance(active->worldPoint(grabLocal),h.position);
    }
    bool twoHand=false;
    std::array<float,2> grabDistance{};
    std::array<glm::vec3,2> secondLocal{};
    glm::vec3 initialSpan{};
    glm::quat initialHandOrientation{1,0,0,0};
    MenuPlacement* last=nullptr;
    size_t lastHand=0;
    double releasedAt=-1,started=0;
    glm::vec3 initialPosition{},relativeCenter{},grabLocal{};
    glm::quat initialOrientation{1,0,0,0};
    float initialScale=1,initialExtent=1;
};
}
