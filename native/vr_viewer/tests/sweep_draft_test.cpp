#include "sweep_draft.hpp"
#include <cassert>
#include <iostream>

using namespace nadoc_vr;
int main() {
    SweepDraft draft;
    assert(draft.step==1 && draft.pointsNm.size()==2 && draft.selected==1);
    assert(!draft.movePoint(0,{1,2,3}));
    assert(!draft.adjustPoint(1,3,1));
    assert(draft.adjustPoint(1,0,1));assert(draft.pointsNm[1]==glm::vec3(1,0,10));
    assert(draft.addPoint());assert(draft.pointsNm.back()==glm::vec3(2,0,20));
    assert(draft.addPoint());assert(draft.pointsNm.back()==glm::vec3(3,0,30));
    // Deleting an interior selection preserves the following point and origin.
    draft.select(1);assert(draft.deleteSelectedPoint());
    assert(draft.pointsNm[1]==glm::vec3(2,0,20) && draft.pointsNm.back()==glm::vec3(3,0,30));
    draft.select(0);assert(!draft.deleteSelectedPoint());
    draft.select(2);assert(draft.deleteSelectedPoint());
    draft.select(1);assert(draft.deleteSelectedPoint());assert(!draft.validPath());
    assert(draft.addPoint() && draft.validPath());
    assert(!draft.movePoint(1,{std::numeric_limits<float>::infinity(),0,0}));
    assert(!draft.movePoint(1,{10001,0,0}));
    assert(draft.movePoint(1,{9999,0,0}));assert(!draft.addPoint());
    // Radial deletion removes the appended endpoint regardless of selection.
    draft.reset();assert(draft.addPoint());assert(draft.addPoint());
    const auto firstPoints=std::vector<glm::vec3>(draft.pointsNm.begin(),draft.pointsNm.begin()+3);
    draft.select(1);assert(draft.deleteLastPoint());
    assert(draft.pointsNm==firstPoints && draft.selected==1);
    draft.select(2);assert(draft.deleteLastPoint());assert(draft.selected==1);
    draft.select(0);assert(draft.deleteLastPoint());
    assert(draft.pointsNm==std::vector<glm::vec3>{glm::vec3(0)} && draft.selected==0);
    const auto lastRevision=draft.revision;
    assert(!draft.deleteLastPoint() && draft.revision==lastRevision);
    draft.reset();draft.freeDrawArmed=true;assert(!draft.deleteLastPoint());
    draft.freeDrawArmed=false;draft.drawing=true;assert(!draft.deleteLastPoint());
    draft.reset();
    assert(draft.next());assert(!draft.next());
    draft.armFreeDraw();assert(draft.freeDrawArmed && draft.pointsNm.size()==1);
    assert(!draft.addPoint());assert(!draft.validPath());
    // Drawing can start anywhere; the stroke is relative to that first sample.
    assert(draft.beginStroke({100,200,300}));assert(draft.drawing);
    for(int i=1;i<=100;++i)draft.appendStroke({100,200,300+float(i)*.2F});
    assert(draft.finishStroke());assert(!draft.drawing && !draft.freeDrawArmed);
    assert(draft.pointsNm.size()==2 && draft.pointsNm.front()==glm::vec3(0));
    assert(glm::length(draft.pointsNm.back()-glm::vec3(0,0,20))<1e-5F);
    draft.armFreeDraw();draft.beginStroke({7,8,9});
    assert(!draft.finishStroke());assert(draft.pointsNm.size()==1 && !draft.validPath());
    draft.armFreeDraw();draft.beginStroke({0,0,0});draft.appendStroke({0,0,10});
    assert(!draft.appendStroke({10001,0,0}) && draft.strokeInvalid);
    assert(!draft.finishStroke() && !draft.validPath());
    draft.armFreeDraw();draft.beginStroke({0,0,0});draft.appendStroke({0,0,8});
    assert(draft.previous());assert(!draft.drawing && !draft.freeDrawArmed);
    draft.reset({10,0,0});assert(draft.pointsNm[1]==glm::vec3(10,0,0));

    // Equal treatment of X/Y/Z removes high-frequency 3D jitter without
    // flattening the intended curve into a plane.
    std::vector<glm::vec3> noisy;
    for(int i=0;i<=400;++i) {
        const float t=float(i)/400,phase=t*glm::two_pi<float>();
        const float noise=(i==0 || i==400)?0.F:.45F*std::sin(i*1.7F);
        noisy.push_back({8*std::sin(phase)+noise,8*(1-std::cos(phase))+.6F*noise,30*t-noise});
    }
    auto knots=smoothSweepStroke(noisy);
    assert(knots.size()>=5 && knots.size()<32 && knots.front()==glm::vec3(0));
    assert(glm::length(knots.back()-noisy.back())<1e-6F);
    const auto smooth=sampleSweepPath(knots,501);assert(smooth.size()==501);
    float maxError=0;
    for(const auto p:smooth) {
        float best=std::numeric_limits<float>::max();
        for(int i=0;i<=1000;++i) {
            const float t=float(i)/1000,phase=t*glm::two_pi<float>();
            best=std::min(best,glm::length(p-glm::vec3(8*std::sin(phase),8*(1-std::cos(phase)),30*t)));
        }
        maxError=std::max(maxError,best);
    }
    assert(maxError<1.5F);
    FreeDrawSettings limited;limited.maxPoints=6;
    assert(smoothSweepStroke(noisy,limited).size()<=6);
    noisy[200].x=std::numeric_limits<float>::quiet_NaN();assert(smoothSweepStroke(noisy).empty());
    assert(smoothSweepStroke({{1,2,3},{1,2,3}}).empty());

    // Natural cubic: equal chord lengths make the first-span midpoint exact.
    const std::vector<glm::vec3> curve{{0,0,0},{10,0,10},{20,10,10}};
    const auto sampled=sampleSweepPath(curve,5);
    assert(sampled.size()==5);
    assert(glm::length(sampled[1]-glm::vec3(5,-.9375F,5.9375F))<1e-4F);
    assert(glm::length(sampled[2]-curve[1])<1e-4F);
    assert(sampleSweepPath({{0,0,0},{0,0,0}}).empty());
    const std::vector<glm::vec3> straight{{0,0,0},{0,0,10}};
    const auto cloud=sweepPreviewCloud(straight,{{2,0,0},{-2,0,0}},8,16);
    assert(cloud.size()==16 && cloud.front()==glm::vec3(2,0,0) && cloud.back()==glm::vec3(-2,0,10));
    const auto bentCloud=sweepPreviewCloud(curve,{{2,0,0}},5,100);
    for(size_t i=0;i<bentCloud.size();++i)assert(std::abs(glm::length(bentCloud[i]-sampled[i])-2)<1e-4F);
    assert(sweepPreviewCloud(curve,{{1,0,0}},128,0).empty());

    const std::vector<glm::vec3> handles{{0,0,-2},{0,0,-4},{1,0,-2}};
    const auto hit=sweepPointRayHit(handles,{0,0,0},{0,0,-2},.2F);
    assert(hit && hit->index==0 && std::abs(hit->distance-1.8F)<1e-4F);
    assert(!sweepPointRayHit(handles,{0,0,0},{0,0,1},.2F));
    SweepPointDrag drag;
    assert(!drag.begin(0,handles[0],{0,0,0},{0,0,-1}));
    assert(drag.begin(1,handles[1],{.1F,0,0},{0,0,-1}));
    assert(glm::length(*drag.update({.1F,0,0},{0,0,-1})-handles[1])<1e-6F);
    assert(glm::length(*drag.update({1.1F,2,0},{0,0,-1})-glm::vec3(1,2,-4))<1e-6F);
    drag.cancel();assert(!drag.update({0,0,0},{0,0,-1}));
    std::cout<<"Sweep draft, natural spline, smoothing, cloud, picking and drag passed\n";
}
