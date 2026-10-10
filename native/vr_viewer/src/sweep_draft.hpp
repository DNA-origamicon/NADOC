#pragma once
#include <glm/glm.hpp>
#include <glm/gtx/quaternion.hpp>
#include <glm/gtx/euler_angles.hpp>
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <limits>
#include <optional>
#include <string>
#include <utility>
#include <vector>

namespace nadoc_vr {
inline bool finiteSweepPoint(glm::vec3 p) {
    return std::isfinite(p.x) && std::isfinite(p.y) && std::isfinite(p.z);
}
inline bool boundedSweepPoint(glm::vec3 p) {
    return finiteSweepPoint(p) && glm::all(glm::lessThanEqual(glm::abs(p),glm::vec3(10000.F)));
}
struct FreeDrawSettings {
    // All distances are model nanometres. These are adjustable stress-test
    // defaults, not a calibrated estimate of human or controller accuracy.
    float sampleSpacingNm=.15F;
    float smoothingRadiusNm=3.6F;
    float simplifyToleranceNm=1.5F;
    float minimumStrokeLengthNm=1.F;
    size_t maxPoints=64;
    size_t maxSamples=8192;
};
inline float sweepSegmentDistanceSquared(glm::vec3 p,glm::vec3 a,glm::vec3 b) {
    const auto delta=b-a;
    const float length=glm::dot(delta,delta);
    const float t=length>1e-12F?std::clamp(glm::dot(p-a,delta)/length,0.F,1.F):0.F;
    const auto d=p-(a+t*delta);return glm::dot(d,d);
}
inline std::vector<glm::vec3> resampleSweepPolyline(const std::vector<glm::vec3>& points,float spacing,size_t limit=8192) {
    if(points.size()<2 || limit<2)return points;
    std::vector<float> distance(points.size());
    for(size_t i=1;i<points.size();++i)distance[i]=distance[i-1]+glm::length(points[i]-points[i-1]);
    if(distance.back()<1e-6F)return {points.front()};
    const size_t count=std::min(limit,std::max(size_t(2),size_t(std::ceil(distance.back()/std::max(spacing,1e-3F)))+1));
    std::vector<glm::vec3> result;result.reserve(count);size_t span=1;
    for(size_t i=0;i<count;++i) {
        const float d=distance.back()*float(i)/float(count-1);
        while(span+1<points.size() && distance[span]<d)++span;
        const float range=distance[span]-distance[span-1];
        result.push_back(glm::mix(points[span-1],points[span],range>1e-8F?(d-distance[span-1])/range:0.F));
    }
    result.front()=points.front();result.back()=points.back();return result;
}
inline std::vector<glm::vec3> simplifySweepPolyline(const std::vector<glm::vec3>& points,float tolerance) {
    if(points.size()<3)return points;
    std::vector<bool> keep(points.size());keep.front()=keep.back()=true;
    std::vector<std::pair<size_t,size_t>> spans{{0,points.size()-1}};
    const float limit=tolerance*tolerance;
    while(!spans.empty()) {
        const auto [first,last]=spans.back();spans.pop_back();
        float furthest=limit;size_t index=first;
        for(size_t i=first+1;i<last;++i) {
            const float distance=sweepSegmentDistanceSquared(points[i],points[first],points[last]);
            if(distance>furthest){furthest=distance;index=i;}
        }
        if(index!=first){keep[index]=true;spans.emplace_back(first,index);spans.emplace_back(index,last);}
    }
    std::vector<glm::vec3> result;
    for(size_t i=0;i<points.size();++i)if(keep[i])result.push_back(points[i]);
    return result;
}
inline std::vector<glm::vec3> smoothSweepStroke(const std::vector<glm::vec3>& samples,const FreeDrawSettings& settings={}) {
    std::vector<glm::vec3> clean;clean.reserve(std::min(samples.size(),settings.maxSamples));
    for(const auto p:samples) {
        if(!finiteSweepPoint(p))return {}; // A tracking gap must never be bridged.
        if(clean.empty() || glm::length(p-clean.back())>1e-6F)clean.push_back(p);
        if(clean.size()>=std::max(size_t(2),settings.maxSamples))break;
    }
    if(clean.size()<2)return {};
    const auto origin=clean.front();
    for(auto& p:clean){p-=origin;if(!boundedSweepPoint(p))return {};}
    // Component-wise median rejects isolated tracking spikes before distance
    // resampling. Three dimensions are treated equally, including depth.
    auto filtered=clean;
    for(size_t i=2;i+2<clean.size();++i)for(int axis=0;axis<3;++axis) {
        std::array<float,5> window{};
        for(size_t j=0;j<5;++j)window[j]=clean[i+j-2][axis];
        std::nth_element(window.begin(),window.begin()+2,window.end());filtered[i][axis]=window[2];
    }
    const float spacing=std::max(.01F,settings.sampleSpacingNm);
    filtered=resampleSweepPolyline(filtered,spacing,std::max(size_t(2),settings.maxSamples));
    float length=0;for(size_t i=1;i<filtered.size();++i)length+=glm::length(filtered[i]-filtered[i-1]);
    if(length<settings.minimumStrokeLengthNm || filtered.size()<2)return {};
    const float interval=length/float(filtered.size()-1);
    const float radius=std::clamp(settings.smoothingRadiusNm,0.F,100.F);
    const size_t window=std::min(filtered.size()-1,size_t(std::ceil(2*radius/std::max(interval,.001F))));
    auto smoothed=filtered;
    for(size_t i=1;i+1<filtered.size() && radius>0;++i) {
        glm::vec3 sum{};float weights=0;
        const size_t first=i>window?i-window:0,last=std::min(filtered.size()-1,i+window);
        for(size_t j=first;j<=last;++j) {
            const float d=(float(j)-float(i))*interval/radius;
            const float weight=std::exp(-.5F*d*d);sum+=filtered[j]*weight;weights+=weight;
        }
        smoothed[i]=sum/std::max(weights,1e-9F);
    }
    // Retain both endpoints, then represent the filtered stroke with a small
    // editable knot set. Raising tolerance provides a bounded point list.
    const size_t maxPoints=std::clamp(settings.maxPoints,size_t(2),size_t(256));
    float tolerance=std::max(.001F,settings.simplifyToleranceNm);
    auto result=simplifySweepPolyline(smoothed,tolerance);
    while(result.size()>maxPoints){tolerance*=1.35F;result=simplifySweepPolyline(smoothed,tolerance);}
    if(result.size()<2 || glm::length(result.back()-result[result.size()-2])<1e-6F)return {};
    result.front()=glm::vec3(0);return result;
}

// Octagonal helix envelopes give a stable outer outline, including thin footprints.
inline std::vector<glm::vec2> sweepSectionHull(const std::vector<glm::vec2>& cells) {
    std::vector<glm::vec2> points;points.reserve(cells.size()*8);
    for(const auto c:cells)for(int i=0;i<8;++i) {
        const float a=glm::two_pi<float>()*i/8;points.push_back(c+glm::vec2(std::cos(a),std::sin(a)));
    }
    std::sort(points.begin(),points.end(),[](auto a,auto b){return a.x<b.x || (a.x==b.x && a.y<b.y);});
    auto half=[](const auto& sorted) {
        std::vector<glm::vec2> result;
        auto cross=[](auto a,auto b,auto c){const auto u=b-a,v=c-a;return u.x*v.y-u.y*v.x;};
        for(const auto p:sorted){while(result.size()>1 && cross(result[result.size()-2],result.back(),p)<=0)result.pop_back();result.push_back(p);}
        if(!result.empty())result.pop_back();
        return result;
    };
    auto result=half(points);std::reverse(points.begin(),points.end());const auto upper=half(points);
    result.insert(result.end(),upper.begin(),upper.end());return result;
}
inline glm::mat3 sweepBasis(glm::vec3 normal) {
    normal=glm::normalize(normal);
    const auto right=std::abs(normal.x)>.9F?glm::vec3(0,1,0):glm::vec3(1,0,0);
    return {right,glm::cross(normal,right),normal};
}
inline glm::mat3 sweepOrientation(glm::vec3 degrees,glm::vec3 normal={0,0,1}) {
    const auto r=glm::radians(degrees);
    return sweepBasis(normal)*glm::mat3(glm::eulerAngleYXZ(r.y,r.x,r.z));
}
inline glm::vec3 sweepAngles(glm::mat3 frame,glm::vec3 normal={0,0,1}) {
    float y,x,z;glm::extractEulerAngleYXZ(glm::mat4(glm::transpose(sweepBasis(normal))*frame),y,x,z);
    return glm::degrees(glm::vec3(x,y,z));
}
inline glm::vec3 snapSweepAngles(glm::vec3 angles) {
    return glm::round(angles/15.F)*15.F;
}
struct SweepDraft {
    int step=1;
    std::vector<glm::vec3> pointsNm{{0,0,0},{0,0,10}};
    std::vector<std::optional<glm::vec3>> orientations{std::nullopt,std::nullopt};
    size_t selected=1;
    bool directionControlled(size_t i) const { return i<orientations.size() && orientations[i].has_value(); }
    bool orient(size_t i,std::optional<glm::vec3> value) {
        if(i>=pointsNm.size() || drawing || freeDrawArmed || (value && !finiteSweepPoint(*value)))return false;
        orientations.resize(pointsNm.size());
        if(value)value=snapSweepAngles(*value);
        if(orientations[i]==value)return false;
        orientations[i]=value;strokeNm.clear();++revision;return true;
    }
    FreeDrawSettings smoothing;
    float smoothingStrength=1.F;
    bool freeDrawArmed=false,drawing=false,strokeInvalid=false;
    std::vector<glm::vec3> strokeNm;
    uint64_t revision=0;
    glm::vec3 strokeStartNm{};
    void reset(glm::vec3 direction={0,0,10}) {
        step=1;pointsNm={{0,0,0},boundedSweepPoint(direction)&&glm::length(direction)>1e-6F?direction:glm::vec3(0,0,10)};
        orientations.assign(2,std::nullopt);
        selected=1;freeDrawArmed=drawing=strokeInvalid=false;strokeNm.clear();++revision;
    }
    bool next(){if(step!=1)return false;step=2;++revision;return true;}
    bool previous(){if(step!=2)return false;step=1;freeDrawArmed=drawing=false;strokeNm.clear();++revision;return true;}
    bool select(size_t index){if(index>=pointsNm.size())return false;selected=index;return true;}
    bool movePoint(size_t index,glm::vec3 value) {
        if(index>=pointsNm.size() || !boundedSweepPoint(value) || drawing)return false;
        if(glm::length(pointsNm[index]-value)<1e-7F)return false;
        pointsNm[index]=value;strokeNm.clear();strokeInvalid=false;++revision;return true;
    }
    bool adjustPoint(size_t index,int axis,float deltaNm) {
        if(axis<0 || axis>2 || index>=pointsNm.size() || !std::isfinite(deltaNm))return false;
        auto p=pointsNm[index];p[axis]+=deltaNm;return movePoint(index,p);
    }
    bool addPoint() {
        if(drawing || freeDrawArmed || pointsNm.size()>=256)return false;
        if(pointsNm.empty())pointsNm.push_back(glm::vec3(0));
        auto delta=pointsNm.size()>1?pointsNm.back()-pointsNm[pointsNm.size()-2]:glm::vec3(0,0,10);
        if(glm::length(delta)<1e-6F)delta={0,0,10};
        if(!boundedSweepPoint(pointsNm.back()+delta))return false;
        pointsNm.push_back(pointsNm.back()+delta);orientations.resize(pointsNm.size());selected=pointsNm.size()-1;strokeInvalid=false;++revision;return true;
    }
    bool deleteSelectedPoint() {
        if(drawing || freeDrawArmed || pointsNm.size()<=1 || selected==0 || selected>=pointsNm.size())return false;
        orientations.resize(pointsNm.size());orientations.erase(orientations.begin()+std::ptrdiff_t(selected));
        pointsNm.erase(pointsNm.begin()+std::ptrdiff_t(selected));selected=std::min(selected,pointsNm.size()-1);strokeInvalid=false;++revision;return true;
    }
    bool deleteLastPoint() {
        if(drawing || freeDrawArmed || pointsNm.size()<=1)return false;
        pointsNm.pop_back();orientations.resize(pointsNm.size());selected=std::min(selected,pointsNm.size()-1);strokeInvalid=false;++revision;return true;
    }
    bool validPath() const {
        if(pointsNm.size()<2 || pointsNm.size()>256 || freeDrawArmed || drawing)return false;
        for(size_t i=0;i<pointsNm.size();++i)
            if(!boundedSweepPoint(pointsNm[i]) || (i && glm::length(pointsNm[i]-pointsNm[i-1])<1e-6F))return false;
        return true;
    }
    void armFreeDraw() {
        if(step!=2)return;
        pointsNm={pointsNm.empty()?glm::vec3(0):pointsNm.front()};orientations.assign(1,std::nullopt);selected=0;strokeNm.clear();freeDrawArmed=true;drawing=strokeInvalid=false;++revision;
    }
    bool beginStroke(glm::vec3 controllerNm) {
        if(!freeDrawArmed || drawing || !finiteSweepPoint(controllerNm))return false;
        strokeStartNm=controllerNm;strokeNm={pointsNm.front()};drawing=true;strokeInvalid=false;++revision;return true;
    }
    bool appendStroke(glm::vec3 controllerNm) {
        if(!drawing)return false;
        if(!finiteSweepPoint(controllerNm)){strokeInvalid=true;return false;}
        const auto p=pointsNm.front()+controllerNm-strokeStartNm;
        if(!boundedSweepPoint(p)){strokeInvalid=true;return false;}
        if(glm::length(p-strokeNm.back())<std::max(.001F,smoothing.sampleSpacingNm))return false;
        if(strokeNm.size()>=std::max(size_t(2),smoothing.maxSamples)) {
            // Keep the full trajectory within a fixed storage budget.
            std::vector<glm::vec3> reduced;reduced.reserve(strokeNm.size()/2+1);
            for(size_t i=0;i<strokeNm.size();i+=2)reduced.push_back(strokeNm[i]);
            strokeNm=std::move(reduced);
        }
        strokeNm.push_back(p);++revision;return true;
    }
    bool finishStroke() {
        if(!drawing)return false;
        drawing=freeDrawArmed=false;
        auto result=strokeInvalid?std::vector<glm::vec3>{}:smoothSweepStroke(strokeNm,smoothing);
        for(auto& p:result){p+=pointsNm.front();if(!boundedSweepPoint(p)){result.clear();break;}}
        if(result.size()<2){pointsNm={pointsNm.front()};selected=0;++revision;return false;}
        pointsNm=std::move(result);orientations.assign(pointsNm.size(),std::nullopt);selected=pointsNm.size()-1;++revision;return true;
    }
    void cancelStroke(){drawing=freeDrawArmed=strokeInvalid=false;strokeNm.clear();++revision;}
};

struct SweepPathSample {glm::vec3 position{},tangent{0,0,1};};
// Chord-length parameterization and natural boundary conditions match
// backend/core/sweep_path.py. Preview samples are bounded and display-only.
inline std::vector<SweepPathSample> sampleSweepPathDetailed(const std::vector<glm::vec3>& points,size_t count=128,
    const std::vector<std::optional<glm::vec3>>& orientations={},glm::vec3 normal={0,0,1}) {
    const size_t n=points.size();if(n<2 || n>256)return {};
    std::vector<float> knots(n),lower(n),diagonal(n),upper(n);
    std::vector<glm::vec3> second(n),rhs(n);
    for(size_t i=0;i<n;++i) {
        if(!finiteSweepPoint(points[i]))return {};
        if(i){const float h=glm::length(points[i]-points[i-1]);if(h<1e-6F)return {};knots[i]=knots[i-1]+h;}
    }
    diagonal.front()=diagonal.back()=1;
    for(size_t i=1;i+1<n;++i) {
        const float before=knots[i]-knots[i-1],after=knots[i+1]-knots[i];
        lower[i]=before;diagonal[i]=2*(before+after);upper[i]=after;
        rhs[i]=6.F*((points[i+1]-points[i])/after-(points[i]-points[i-1])/before);
    }
    for(size_t i=1;i<n;++i){const float factor=lower[i]/diagonal[i-1];diagonal[i]-=factor*upper[i-1];rhs[i]-=factor*rhs[i-1];}
    second.back()=rhs.back()/diagonal.back();
    for(size_t i=n-1;i-->0;)second[i]=(rhs[i]-upper[i]*second[i+1])/diagonal[i];
    std::vector<glm::vec3> derivatives(n);
    const bool controlled=std::any_of(orientations.begin(),orientations.end(),[](const auto& a){return a.has_value();});
    for(size_t i=0;i<n;++i) {
        const size_t j=std::min(i,n-2);const float h=knots[j+1]-knots[j];
        derivatives[i]=(points[j+1]-points[j])/h+(i==n-1?(second[j]+2.F*second[j+1]):(-2.F*second[j]-second[j+1]))*(h/6.F);
        if(i<orientations.size() && orientations[i])derivatives[i]=sweepOrientation(*orientations[i],normal)[2]*std::max(1.F,glm::length(derivatives[i]));
    }
    count=std::clamp(count,size_t(2),size_t(4096));
    std::vector<SweepPathSample> result;result.reserve(count);size_t span=0;
    for(size_t i=0;i<count;++i) {
        const float t=knots.back()*float(i)/float(count-1);
        while(span+2<n && knots[span+1]<t)++span;
        const float h=knots[span+1]-knots[span],a=(knots[span+1]-t)/h,b=(t-knots[span])/h;
        auto p=a*points[span]+b*points[span+1]+((a*a*a-a)*second[span]+(b*b*b-b)*second[span+1])*(h*h/6.F);
        auto derivative=(points[span+1]-points[span])/h+((1-3*a*a)*second[span]+(3*b*b-1)*second[span+1])*(h/6.F);
        if(controlled) {
            const float t=b,t2=t*t,t3=t2*t;
            p=(2*t3-3*t2+1)*points[span]+(t3-2*t2+t)*h*derivatives[span]+(-2*t3+3*t2)*points[span+1]+(t3-t2)*h*derivatives[span+1];
            derivative=((6*t2-6*t)*points[span]+(3*t2-4*t+1)*h*derivatives[span]+(-6*t2+6*t)*points[span+1]+(3*t2-2*t)*h*derivatives[span+1])/h;
        }
        if(glm::length(derivative)<1e-8F)return {};
        result.push_back({p,glm::normalize(derivative)});
    }
    return result;
}
inline std::vector<glm::vec3> sampleSweepPath(const std::vector<glm::vec3>& points,size_t count=128) {
    std::vector<glm::vec3> result;
    for(const auto& sample:sampleSweepPathDetailed(points,count))result.push_back(sample.position);
    return result;
}
inline std::vector<glm::vec3> sweepPreviewCloud(const std::vector<glm::vec3>& points,
    const std::vector<glm::vec3>& crossSectionOffsetsNm,size_t samples=128,size_t budget=8192,
    glm::vec3 sourceTangent={0,0,1}) {
    if(crossSectionOffsetsNm.empty() || budget<2 || glm::length(sourceTangent)<1e-6F)return {};
    const size_t helices=std::min(crossSectionOffsetsNm.size(),budget/2);
    samples=std::min(samples,budget/helices);
    const auto path=sampleSweepPathDetailed(points,samples);if(path.empty())return {};
    std::vector<glm::vec3> result;result.reserve(path.size()*helices);
    auto rotation=glm::rotation(glm::normalize(sourceTangent),path.front().tangent);
    for(size_t i=0;i<path.size();++i) {
        if(i)rotation=glm::normalize(glm::rotation(path[i-1].tangent,path[i].tangent)*rotation);
        for(size_t h=0;h<helices;++h) {
            const size_t index=h*crossSectionOffsetsNm.size()/helices;
            result.push_back(path[i].position+rotation*crossSectionOffsetsNm[index]);
        }
    }
    return result;
}
struct SweepPointHit {size_t index=0;float distance=0;glm::vec3 position{};};
inline std::optional<SweepPointHit> sweepPointRayHit(const std::vector<glm::vec3>& points,
    glm::vec3 origin,glm::vec3 direction,float radius) {
    if(!finiteSweepPoint(origin) || !finiteSweepPoint(direction) || glm::length(direction)<1e-6F || !std::isfinite(radius) || radius<=0)return std::nullopt;
    direction=glm::normalize(direction);std::optional<SweepPointHit> hit;
    for(size_t i=0;i<points.size();++i) {
        if(!finiteSweepPoint(points[i]))continue;
        const auto d=points[i]-origin;const float along=glm::dot(d,direction);
        const float discriminant=radius*radius-(glm::dot(d,d)-along*along);
        if(discriminant<0)continue;
        const float near=along-std::sqrt(discriminant),far=along+std::sqrt(discriminant);
        if(far<0)continue;
        const float distance=std::max(0.F,near);
        if(!hit || distance<hit->distance)hit=SweepPointHit{i,distance,origin+direction*distance};
    }
    return hit;
}
struct SweepPointDrag {
    bool active=false;size_t index=0;float distance=0;glm::vec3 offset{};
    bool begin(size_t pointIndex,glm::vec3 point,glm::vec3 origin,glm::vec3 direction) {
        active=false;
        if(!finiteSweepPoint(point) || !finiteSweepPoint(origin) || !finiteSweepPoint(direction) || glm::length(direction)<1e-6F)return false;
        direction=glm::normalize(direction);distance=glm::dot(point-origin,direction);
        if(distance<0)return false;
        active=true;index=pointIndex;offset=point-(origin+direction*distance);return true;
    }
    std::optional<glm::vec3> update(glm::vec3 origin,glm::vec3 direction) const {
        if(!active || !finiteSweepPoint(origin) || !finiteSweepPoint(direction) || glm::length(direction)<1e-6F)return std::nullopt;
        return origin+glm::normalize(direction)*distance+offset;
    }
    void cancel(){active=false;}
};
}
