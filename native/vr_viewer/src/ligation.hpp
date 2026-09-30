#pragma once
#include "interaction.hpp"
#include <fstream>
#include <optional>

namespace nadoc_vr {
inline constexpr std::array<const char*,4> kRadialEditLabels{"LIGATE","NICK","UNDO","REDO"};
inline constexpr bool radialEditEnabled(size_t item) { return item<4; }

class Ligation {
 public:
    struct End {
        int role=0, strand=0;
        std::string identity;
        glm::vec3 position{}, tangent{}, offset{};
    };
    struct Bond { glm::vec3 a{},b{},offsetA{},offsetB{}; };
    std::vector<Bond> bonds;
    bool nickActive=false;
    std::array<std::optional<size_t>,2> nickHover{};
    std::array<float,2> squeeze{};
    std::string committedAction="ligate";
    std::vector<End> ends;
    bool active=false, waiting=false;
    uint64_t version=0, sequence=0, committedVersion=0;
    size_t source=0, committedSource=0, committedTarget=0;
    std::optional<size_t> hand, target;
    std::array<std::optional<size_t>,2> hover{};
    glm::mat4 startModel{1};
    glm::vec3 loosePoint{};
    std::string status="ready";
    bool incompatible=false;

    void cancel() {nickHover={};hand.reset();target.reset();hover={};incompatible=false;}
    void setActive(bool value) {cancel();active=value;nickActive=false;}
    void poll(const std::string& path,glm::vec3 center,float scale,glm::vec3 origin) {
        if(path.empty())return;
        std::ifstream input(path+".ligation");
        std::string magic,nextStatus;uint64_t next;size_t count;
        if(!(input>>magic>>next>>nextStatus>>count) || magic!="NADOC_LIGATION_1" || count>32768 || next==version)return;
        std::vector<End> loaded;
        for(size_t i=0;i<count;++i) {
            End e;
            if(!(input>>e.role>>e.strand>>e.identity>>e.position.x>>e.position.y>>e.position.z
                >>e.tangent.x>>e.tangent.y>>e.tangent.z>>e.offset.x>>e.offset.y>>e.offset.z))return;
            if((e.role!=3 && e.role!=5)||e.strand<0||e.identity.size()>2048)return;
            for(int j=0;j<3;++j)if(!std::isfinite(e.position[j])||!std::isfinite(e.tangent[j])||!std::isfinite(e.offset[j]))return;
            e.position=(e.position-center)*scale+origin;e.offset*=scale;
            loaded.push_back(e);
        }
        std::string bondMagic;size_t bondCount=0;std::vector<Bond> newBonds;
        if(input>>bondMagic>>bondCount) {
            if(bondMagic!="BONDS" || bondCount>1000000)return;
            for(size_t i=0;i<bondCount;++i) {
                Bond b;
                for(auto* v:{&b.a,&b.b,&b.offsetA,&b.offsetB}) {
                    if(!(input>>v->x>>v->y>>v->z))return;
                    for(int j=0;j<3;++j)if(!std::isfinite((*v)[j]))return;
                }
                b.a=(b.a-center)*scale+origin;b.b=(b.b-center)*scale+origin;
                b.offsetA*=scale;b.offsetB*=scale;newBonds.push_back(b);
            }
        }
        bonds=std::move(newBonds);
        cancel();waiting=false;version=next;ends=std::move(loaded);status=nextStatus;
    }
    glm::vec3 point(size_t i,const glm::mat4& model) const {
        const auto& e=ends[i];return glm::vec3(model*glm::vec4(e.position,1));
    }
    bool compatible(size_t a,size_t b) const {
        return a!=b && ends[a].role!=ends[b].role && ends[a].strand!=ends[b].strand;
    }
    std::optional<size_t> nearest(glm::vec3 p,float radius,const glm::mat4& model,bool pairOnly=false) const {
        std::optional<size_t> result;float best=radius;
        for(size_t i=0;i<ends.size();++i) {
            if(pairOnly && !compatible(source,i))continue;
            const float d=glm::distance(p,point(i,model));
            if(d<best){best=d;result=i;}
        }
        return result;
    }
    template<class Select,class Commit> void input(const std::array<HandPose,2>& hands,
        const std::array<glm::vec3,2>& centers,const std::array<float,2>& radii,
        const std::array<bool,2>& clicked,const std::array<bool,2>& pressed,
        std::array<bool,2>& blocked,const glm::mat4& model,bool enabled,Select select,Commit commit) {
        hover={};
        if(!active)return;
        if(hand) {
            const size_t h=*hand;
            const bool uiBlocked=blocked[h];blocked[h]=true;
            // Tracking loss, mode/menu change and scene movement must not be a release.
            if(!enabled||uiBlocked||!hands[h].valid||model!=startModel) {cancel();status="cancelled";return;}
            loosePoint=centers[h];target=nearest(loosePoint,radii[h],model,true);
            incompatible=!target && nearest(loosePoint,radii[h],model).has_value();
            if(!pressed[h]) {
                if(target) {
                    committedAction="ligate";committedVersion=version;committedSource=source;committedTarget=*target;
                    waiting=true;status="committing";++sequence;commit();
                } else status="cancelled";
                cancel();
            }
            return;
        }
        for(size_t h=0;h<2;++h) {
            if(blocked[h]||!hands[h].valid)continue;
            blocked[h]=true; // Ligate owns end picks; do not resize or clear selection.
            if(!enabled||waiting)continue;
            hover[h]=nearest(centers[h],radii[h],model);
            if(hover[h]&&clicked[h]) {
                source=*hover[h];hand=h;startModel=model;
                loosePoint=centers[h];status="dragging";select(ends[source].identity,h);break;
            }
        }
    }
    glm::vec3 bondPoint(size_t i,bool second,const glm::mat4& model) const {
        const auto& b=bonds[i];
        return glm::vec3(model*glm::vec4((second?b.b:b.a),1));
    }
    template<class Commit> void request(const std::string& action,size_t index,Commit commit) {
        if(waiting||!version)return;
        cancel();committedAction=action;committedVersion=version;committedSource=index;committedTarget=0;
        waiting=true;status="committing";++sequence;commit();
    }
    template<class Commit> void nickInput(const std::array<HandPose,2>& hands,
        const std::array<glm::vec3,2>& centers,const std::array<float,2>& radii,
        const std::array<float,2>& values,const std::array<bool,2>& clicked,
        std::array<bool,2>& blocked,const glm::mat4& model,bool enabled,Commit commit) {
        nickHover={};squeeze=values;
        if(!nickActive)return;
        for(size_t h=1;h<2;++h) {
            const bool uiBlocked=blocked[h];blocked[h]=true;
            if(uiBlocked||!enabled||waiting||!hands[h].valid)continue;
            float best=radii[h];
            for(size_t i=0;i<bonds.size();++i) {
                const auto a=bondPoint(i,false,model),b=bondPoint(i,true,model),ab=b-a;
                const float t=glm::dot(ab,ab)>1e-12F?glm::clamp(glm::dot(centers[h]-a,ab)/glm::dot(ab,ab),0.F,1.F):0.F;
                const float d=glm::distance(centers[h],a+t*ab);
                if(d<best){best=d;nickHover[h]=i;}
            }
            if(nickHover[h] && clicked[h]) {request("nick",*nickHover[h],commit);break;}
        }
    }
    static float scissorAngle(float value) {return .65F*(1.F-glm::clamp(value/0.9F,0.F,1.F));}
    template<class Line> void scissors(glm::vec3 center,glm::quat orientation,float value,Line line) const {
        const auto pivot=center-orientation*glm::vec3(0,.022F,0);
        auto stroke=[&](glm::vec3 a,glm::vec3 b,glm::vec3 color) {
            for(float z:{-.001F,0.F,.001F})line(pivot+orientation*(a+glm::vec3(0,0,z)),pivot+orientation*(b+glm::vec3(0,0,z)),color);
        };
        for(float side:{-1.F,1.F}) {
            const float angle=side*scissorAngle(value);
            const glm::vec3 blade{std::sin(angle),std::cos(angle),0},cross{blade.y,-blade.x,0};
            const glm::vec3 color{.65F,.95F,1.F};
            stroke(-blade*.015F,blade*.055F,color);
            stroke(cross*.004F,blade*.055F,color);
            stroke(cross*.004F,-blade*.015F,color);
            const auto handle=-blade*.03F;
            for(int i=0;i<20;++i) {
                const float a=glm::two_pi<float>()*i/20,b=glm::two_pi<float>()*(i+1)/20;
                stroke(handle+.012F*glm::vec3(std::cos(a),std::sin(a),0),handle+.012F*glm::vec3(std::cos(b),std::sin(b),0),{.15F,.8F,1.F});
            }
        }
    }
    template<class Line> void drawNick(const glm::mat4& model,Line line) const {
        if(!nickActive)return;
        for(size_t h=0;h<2;++h)if(nickHover[h]) {
            const auto a=bondPoint(*nickHover[h],false,model),b=bondPoint(*nickHover[h],true,model);
            const glm::vec3 color=glm::mix(glm::vec3(1,.55F,.05F),glm::vec3(1,1,.65F),glm::clamp(squeeze[h],0.F,1.F));
            // Bright core and a spatial halo stay on the actual bond endpoints.
            line(a,b,color);
            for(int i=0;i<12;++i) {
                const float angle=glm::two_pi<float>()*i/12;
                const glm::vec3 offset{.002F*std::cos(angle),.002F*std::sin(angle),0};
                line(a+offset,b+offset,color*.75F);
            }
        }
    }
    glm::vec3 previewEnd(const glm::mat4& model) const {return target?point(*target,model):loosePoint;}
    template<class Line> void draw(const glm::mat4& model,Line line) const {
        if(!active)return;
        auto marker=[&](glm::vec3 p,glm::vec3 color) {
            constexpr float r=.009F;
            for(int plane=0;plane<3;++plane)for(int i=0;i<16;++i) {
                glm::vec3 a{},b{};const int u=plane,v=(plane+1)%3;
                const float t=glm::two_pi<float>()*i/16,tn=glm::two_pi<float>()*(i+1)/16;
                a[u]=r*std::cos(t);a[v]=r*std::sin(t);b[u]=r*std::cos(tn);b[v]=r*std::sin(tn);
                line(p+a,p+b,color);
            }
        };
        for(const auto& h:hover)if(h)marker(point(*h,model),{1,1,.1F});
        if(!hand)return;
        const auto a=point(source,model),b=previewEnd(model);
        marker(a,{.1F,1,.25F});
        const glm::vec3 color=target?glm::vec3(.1F,1,.25F):incompatible?glm::vec3(1,.2F,.1F):glm::vec3(0,.85F,1);
        if(target)marker(b,color);
        const auto chord=b-a;const float distance=glm::length(chord);
        if(distance<1e-6F)return;
        auto axis=glm::mat3(model)*(ends[source].tangent+(target?ends[*target].tangent:ends[source].tangent));
        if(glm::length(axis)<1e-6F)axis={0,0,1};else axis=glm::normalize(axis);
        auto bow=glm::cross(chord/distance,axis);
        bow=glm::length(bow)<1e-6F?axis:glm::normalize(bow);
        // The native scene renders an uninserted forced ligation as a direct
        // bond. Keep the stretched preview on that same segment.
        for(float offset:{-.0015F,0.0F,.0015F})line(a+bow*offset,b+bow*offset,color);
    }
};
}
