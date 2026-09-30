#pragma once
#include "sidebar_menu.hpp"

namespace nadoc_vr {
// Resolve close/overlapping border targets by distance; held grips retain ownership.
template<class Menus,class Feedback>
std::array<bool,2> updateSidebarGrips(Menus& menus,const std::array<HandPose,2>& hands,
        const std::array<bool,2>& clicked,Feedback feedback) {
    const float halfWidth=.515F;
    std::array<int,2> owner{-1,-1},target{-1,-1};
    for(size_t i=0;i<menus.size();++i) {
        auto& m=menus[i];m.gripNearby.fill(false);
        if(!m.open) {m.gripState=GripFrameState::idle;continue;}
        m.placement.update(hands,halfWidth);
        if(m.placement.resizeActive()) owner.fill(int(i));
        else if(m.placement.dragHand()) owner[*m.placement.dragHand()]=int(i);
    }
    for(size_t h=0;h<2;++h) {
        target[h]=owner[h];
        float nearest=MenuPlacement::kBorderGrabDistanceMeters;
        if(owner[h]<0) for(size_t i=0;i<menus.size();++i) if(menus[i].open) {
            const auto b=menus[i].bounds();
            const float distance=menus[i].placement.borderDistanceMeters(hands[h],b.minimum,b.maximum);
            if(distance<=nearest) {nearest=distance;target[h]=int(i);}
        }
        if(target[h]>=0) menus[target[h]].gripNearby[h]=true;
    }
    for(size_t i=0;i<menus.size();++i) {
        auto& m=menus[i];if(!m.open)continue;
        const auto b=m.bounds();
        const bool requested=(clicked[0]&&target[0]==int(i))||(clicked[1]&&target[1]==int(i));
        if(requested && target[0]==int(i) && target[1]==int(i) &&
                m.placement.beginBorderResize(hands,b.minimum,b.maximum)) {
            owner.fill(int(i));feedback(0,.52F);feedback(1,.52F);
        } else for(size_t h=0;h<2;++h) {
            if(clicked[h]&&owner[h]<0&&target[h]==int(i)&&
                    m.placement.beginDrag(h,hands,b.minimum,b.maximum)) {
                owner[h]=int(i);feedback(h,.48F);
            }
        }
        m.placement.update(hands,halfWidth);
        m.gripState=(m.placement.resizeActive()||m.placement.remoteMode()==2)?GripFrameState::resizing:
            (m.placement.dragHand()||m.placement.remoteMode()==1)?GripFrameState::moving:
            (m.gripNearby[0]||m.gripNearby[1]||m.placement.remoteHovered)?GripFrameState::ready:GripFrameState::idle;
    }
    return {owner[0]>=0,owner[1]>=0};
}
}
