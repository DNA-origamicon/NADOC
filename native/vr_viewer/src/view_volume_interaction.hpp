#pragma once
#include "interaction.hpp"

namespace nadoc_vr {
// Geometry remains in launch-rotated document nm. Scene grips only change its
// presentation matrix; triggers edit these records through the inverse matrix.
struct ViewVolumeRecord {
    std::string id,name;
    bool outline=true,enabled=true;
    size_t sides=4;
    std::vector<glm::vec3> points;
    glm::vec3 center{},half{1};
    glm::quat rotation{1,0,0,0};
    bool editable=false;
    std::string representation="full",coloring="strand";
    float opacity=1;
    void rebuild() {
        points.clear();
        for(int cap=0;cap<2;++cap)for(size_t i=0;i<sides;++i) {
            glm::vec3 p;
            if(sides==6) {
                float angle=float(i)*glm::pi<float>()/3, radius=std::min(half.x,half.y);
                p={radius*std::cos(angle),radius*std::sin(angle),cap?half.z:-half.z};
            } else p={i==0||i==3?-half.x:half.x,i<2?-half.y:half.y,cap?half.z:-half.z};
            points.push_back(center+rotation*p);
        }
    }
    size_t faceCount() const {return sides+2;}
    std::vector<size_t> face(size_t index) const {
        if(index<sides)return {index,(index+1)%sides,(index+1)%sides+sides,index+sides};
        std::vector<size_t> vertices;
        for(size_t i=0;i<sides;++i)vertices.push_back(i+(index==sides?0:sides));
        return vertices;
    }
    glm::vec3 normal(size_t index) const {
        if(index>=sides)return {0,0,index==sides?-1.F:1.F};
        if(sides==6) {float a=(float(index)+.5F)*glm::pi<float>()/3;return {std::cos(a),std::sin(a),0};}
        return std::array<glm::vec3,4>{{{0,-1,0},{1,0,0},{0,1,0},{-1,0,0}}}[index];
    }
};

class ViewVolumeInteraction {
 public:
    static constexpr float centroidRange=.075F, faceRange=.05F;
    std::string held;
    std::optional<size_t> hand, resizeFace;
    std::array<std::string,2> nearby{};
    std::array<int,2> nearbyFace{-1,-1};
    glm::vec3 centerInHand{};
    glm::quat rotationInHand{1,0,0,0};
    float resizeStartProjection=0;
    glm::vec3 resizeStartHalf{};

    static glm::mat4 frame(const glm::mat4& model,glm::vec3 center,float scale,glm::vec3 origin) {
        return model*glm::translate(glm::mat4(1),origin-center*scale)*glm::scale(glm::mat4(1),glm::vec3(scale));
    }
    static glm::vec3 point(const glm::mat4& frame,glm::vec3 p) {return glm::vec3(frame*glm::vec4(p,1));}
    static glm::quat orientation(const glm::mat4& frame) {
        return glm::normalize(glm::quat_cast(glm::mat3(frame)/glm::length(glm::vec3(frame[0]))));
    }
    static float faceDistance(const ViewVolumeRecord& e,size_t face,glm::vec3 p) {
        // Distance to the finite convex polygon, not its infinite supporting plane.
        const auto indices=e.face(face);const auto n=e.rotation*e.normal(face);
        const float height=glm::dot(p-e.points[indices[0]],n);
        const auto projected=p-height*n;
        glm::vec3 middle{};for(auto i:indices)middle+=e.points[i];middle/=float(indices.size());
        bool inside=true;float edgeDistance=std::numeric_limits<float>::infinity();
        for(size_t i=0;i<indices.size();++i) {
            const auto a=e.points[indices[i]],b=e.points[indices[(i+1)%indices.size()]],edge=b-a;
            const float ref=glm::dot(glm::cross(edge,middle-a),n);
            if(glm::dot(glm::cross(edge,projected-a),n)*ref < -1e-6F)inside=false;
            const auto closest=a+std::clamp(glm::dot(p-a,edge)/glm::dot(edge,edge),0.F,1.F)*edge;
            edgeDistance=std::min(edgeDistance,glm::length(p-closest));
        }
        return inside?std::abs(height):edgeDistance;
    }
    void cancel() {held.clear();hand.reset();resizeFace.reset();nearby={};nearbyFace={-1,-1};}
    void rebase(const ViewVolumeRecord& e,const HandPose& h,const glm::mat4& f) {
        centerInHand=glm::inverse(h.orientation)*(point(f,e.center)-h.position);
        rotationInHand=glm::normalize(glm::inverse(h.orientation)*orientation(f)*e.rotation);
    }
    float projection(const ViewVolumeRecord& e,const HandPose& h,const glm::mat4& f,size_t face) const {
        const auto local=glm::inverse(e.rotation)*(point(glm::inverse(f),h.position)-e.center);
        return glm::dot(local,e.normal(face));
    }
    template<class Changed,class Feedback>
    std::array<bool,2> input(std::vector<ViewVolumeRecord>& entries,const std::array<HandPose,2>& hands,
        const std::array<bool,2>& clicked,const std::array<bool,2>& pressed,const glm::mat4& f,
        bool allowed,bool sceneGrip,Changed changed,Feedback feedback) {
        std::array<bool,2> claimed{};nearby={};nearbyFace={-1,-1};
        auto current=[&]() -> ViewVolumeRecord* {for(auto& e:entries)if(e.id==held)return &e;return nullptr;};
        auto* e=current();
        if(hand && (!allowed||!e||!e->outline||!hands[*hand].valid||!pressed[*hand])) {
            // Reserve a released/invalid grab for this frame; it cannot click through.
            claimed[*hand]=true;if(resizeFace)claimed[1-*hand]=true;cancel();e=nullptr;
        }
        if(!allowed)return claimed;
        const float worldScale=glm::length(glm::vec3(f[0]));
        if(!hand) {
            for(size_t h=0;h<2;++h)if(hands[h].valid) {
                float distance=centroidRange;
                for(const auto& volume:entries)if(volume.outline&&volume.editable) {
                    float d=glm::length(point(f,volume.center)-hands[h].position);
                    if(d<distance){distance=d;nearby[h]=volume.id;}
                }
            }
            for(size_t h=0;h<2;++h)if(!nearby[h].empty()) {
                claimed[h]=true;
                if(clicked[h]&&!sceneGrip) {
                    hand=h;held=nearby[h];e=current();rebase(*e,hands[h],f);feedback(h);break;
                }
            }
        }
        if(!hand)return claimed;
        const size_t first=*hand,second=1-first;claimed[first]=true;nearby[first]=held;
        if(!hands[second].valid || !pressed[second])resizeFace.reset();
        const auto oldCenter=e->center,oldHalf=e->half;const auto oldRotation=e->rotation;
        if(sceneGrip) {
            // Grip moves the entire scene. Rebase trigger anchors every frame so
            // resuming a trigger drag never cancels that motion or causes a jump.
            rebase(*e,hands[first],f);
            if(resizeFace){resizeStartHalf=e->half;resizeStartProjection=projection(*e,hands[second],f,*resizeFace);}
        } else {
            e->center=point(glm::inverse(f),hands[first].position+hands[first].orientation*centerInHand);
            e->rotation=glm::normalize(glm::inverse(orientation(f))*hands[first].orientation*rotationInHand);
            if(resizeFace) {
                const auto face=*resizeFace;
                const float delta=projection(*e,hands[second],f,face)-resizeStartProjection;
                // Minimum one mm half-extent in physical tracking space.
                const float minimum=.001F/worldScale;
                if(face>=e->sides)e->half.z=std::max(minimum,resizeStartHalf.z+delta);
                else if(e->sides==6) {
                    const float radius=std::max(minimum,std::min(resizeStartHalf.x,resizeStartHalf.y)+delta/std::cos(glm::pi<float>()/6));
                    e->half.x=e->half.y=radius;
                } else {
                    size_t axis=std::abs(e->normal(face).x)>.5F?0:1;
                    e->half[axis]=std::max(minimum,resizeStartHalf[axis]+delta);
                }
            }
            e->rebuild();
        }
        if(resizeFace){claimed[second]=true;nearbyFace[second]=int(*resizeFace);}
        else if(hands[second].valid) {
            float distance=faceRange;const auto p=point(glm::inverse(f),hands[second].position);
            for(size_t i=0;i<e->faceCount();++i) {
                float d=faceDistance(*e,i,p)*worldScale;
                if(d<distance){distance=d;nearbyFace[second]=int(i);}
            }
            if(nearbyFace[second]>=0) {
                claimed[second]=true;
                if(clicked[second]&&!sceneGrip) {
                    resizeFace=size_t(nearbyFace[second]);resizeStartHalf=e->half;
                    resizeStartProjection=projection(*e,hands[second],f,*resizeFace);feedback(second);
                }
            }
        }
        if(glm::length(e->center-oldCenter)>1e-6F || glm::length(e->half-oldHalf)>1e-6F || glm::length(e->rotation-oldRotation)>1e-6F)changed(*e);
        return claimed;
    }
};
}
