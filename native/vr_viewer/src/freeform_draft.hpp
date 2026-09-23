#pragma once
#include "freeform_placement.hpp"
#include "interaction.hpp"
#include <ostream>
#include <glm/gtx/quaternion.hpp>

namespace nadoc_vr {
class FreeformDraft {
  public:
    bool armed() const { return armed_; }
    bool placed() const { return placement_.has_value(); }
    void clear() { armed_=false; placement_.reset(); }
    void arm() { clear(); armed_=true; }
    bool capture(const HandPose& hand, const std::string& plane, const glm::mat4& model,
                 const glm::vec3& center, float scale, const glm::vec3& offset) {
        if (!armed_ || !hand.valid) return false;
        const glm::vec3 axis = plane=="XY" ? glm::vec3(0,0,1) :
            plane=="XZ" ? glm::vec3(0,1,0) : glm::vec3(1,0,0);
        placement_ = trackingToSourcePlacement(hand.position,
            hand.orientation*glm::rotation(axis,glm::vec3(0,0,-1)),model,center,scale,offset);
        if (!placement_) return false;
        armed_=false;
        return true;
    }
    void appendJson(std::ostream& out) const {
        if (!placement_) return;
        const auto& p=placement_->translationNanometers;
        const auto& q=placement_->rotation;
        out << ",\"freeform_placement\":{\"translation_nm\":[" << p.x << ',' << p.y << ',' << p.z
            << "],\"rotation_xyzw\":[" << q.x << ',' << q.y << ',' << q.z << ',' << q.w << "]}";
    }
    template<class Line> void preview(const std::vector<LatticeCell>& cells, bool square,
        const std::string& plane, int length, const glm::mat4& model,
        const glm::vec3& center,float scale,const glm::vec3& offset,Line line) const {
        if (!placement_) return;
        auto point = [&](glm::vec3 local) {
            const auto source=placement_->translationNanometers+placement_->rotation*local;
            return glm::vec3(model*glm::vec4(sourceToNormalizedPoint(source,center,scale,offset),1));
        };
        auto local = [&](float u,float v,float axial) {
            return plane=="XY" ? glm::vec3(u,v,axial) :
                plane=="XZ" ? glm::vec3(u,axial,v) : glm::vec3(axial,u,v);
        };
        const glm::vec3 color(0.2F,0.9F,1.F);
        for (const auto& cell:cells) {
            const auto p=latticeCellOffsetNanometers(cell,{},square);
            const float end=length*kDnaBasePairRiseNanometers;
            line(point(local(p.x,p.y,0)),point(local(p.x,p.y,end)),color);
            for (int i=0;i<12;++i) {
                const float a=i*glm::two_pi<float>()/12,b=(i+1)*glm::two_pi<float>()/12;
                for (float z:{0.F,end}) line(point(local(p.x+std::cos(a),p.y+std::sin(a),z)),
                    point(local(p.x+std::cos(b),p.y+std::sin(b),z)),color);
            }
        }
    }
  private:
    bool armed_=false;
    std::optional<SourceRigidPlacement> placement_;
};
}
