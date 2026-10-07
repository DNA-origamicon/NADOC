#pragma once
#include "sidebar_menu.hpp"
#include <glm/gtx/quaternion.hpp>
#include <iomanip>
#include <tuple>

namespace nadoc_vr {
// Circular arc with a fixed contour and a fixed surface-normal tangent.
struct BendArc {
    glm::vec3 a{}, b{}, tangent{0,0,1}, direction{1,0,0};
    float length=0, angle=0;
    size_t fixedEnd=0;
    glm::mat3 sourceAxes{1};
    glm::vec3 referenceDirection() const {
        // Source axes are exported through the desktop camera rotation too.
        // Project authored X (or Y at the pole), never an export-space axis.
        auto x=sourceAxes[0]-tangent*glm::dot(tangent,sourceAxes[0]);
        if(glm::length(x)<.001F)x=sourceAxes[1]-tangent*glm::dot(tangent,sourceAxes[1]);
        return glm::normalize(x);
    }
    glm::vec3 raw(float t) const {
        if(angle<.00001F)return tangent*(length*t);
        return (tangent*std::sin(angle*t)+direction*(1-std::cos(angle*t)))*(length/angle);
    }
    glm::vec3 point(float t) const {return fixedEnd==0?a+raw(t):b-raw(1-t);}
    glm::vec3 endTangent(float t) const {
        const float phase=angle*(fixedEnd==0?t:1-t);
        return tangent*std::cos(phase)+direction*std::sin(phase);
    }
    void updateEndpoint() {if(fixedEnd==0)b=a+raw(1);else a=b-raw(1);}
    void move(size_t end,glm::vec3 target) {
        fixedEnd=1-end;
        const auto chord=end==1?target-a:b-target;
        if(glm::distance(chord,raw(1))<1e-6F)return;
        const auto transverse=chord-tangent*glm::dot(chord,tangent);
        if(glm::length(transverse)>1e-7F)direction=glm::normalize(transverse);
        // Controller positions outside the two-parameter circular-arc surface
        // project to the nearest attainable endpoint. Never tilt the anchor.
        auto error=[&](float theta) {
            const auto offset=theta<1e-6F?tangent*length:
                (tangent*std::sin(theta)+direction*(1-std::cos(theta)))*(length/theta);
            const auto delta=offset-chord;return glm::dot(delta,delta);
        };
        constexpr int samples=180;
        const float step=glm::radians(359.F)/samples;
        int best=0;
        for(int i=1;i<=samples;++i)if(error(i*step)<error(best*step))best=i;
        float lo=std::max(0.F,(best-1)*step),hi=std::min(glm::radians(359.F),(best+1)*step);
        for(int i=0;i<32;++i) {
            const float left=lo+(hi-lo)/3,right=hi-(hi-lo)/3;
            if(error(left)<error(right))hi=right;else lo=left;
        }
        angle=(lo+hi)*.5F;
        if(error(0)<=error(angle))angle=0;
        updateEndpoint();
    }
};
class BendPanel {
 public:
    bool active=false, posed=false, elements=false, twist=false, selecting=false;
    bool manual=false, clustersOpen=false, defaultPlanes=false;
    size_t clusterPage=0;
    std::vector<std::string> clusters;
    std::string clusterLabel="None";
    std::array<std::optional<size_t>,2> planeHover{};
    std::array<std::optional<glm::vec3>,2> beamEnd{};
    std::array<bool,3> wheelHover{};
    std::array<ThumbwheelControl,3> wheels;
    float grabRayDistance=0;
    size_t savedOffset=0, grabbed=1, wheelIndex=0;
    std::optional<size_t> hand, planeHand, wheelHand;
    std::optional<std::string> pickSlot;
    std::string lastPick, pendingSelection;
    glm::vec3 grabOffset{};
    glm::mat4 startModel{1};
    BendArc arc;
    ThumbwheelControl wheel;
    static bool supports(const std::string& kind) {
        return kind=="cluster" || kind=="strand" || kind=="domain" || kind=="selection" || kind=="end";
    }
    void describeSelection(const std::string& kind,const std::vector<std::string>& owners) {
        if(kind!="selection") {clusterLabel=kind=="none"?"No selection":"Selected "+kind;return;}
        size_t clusters=0,strands=0,domains=0;
        for(const auto& token:owners) {
            clusters+=token.starts_with("%5B%22cluster%22");
            strands+=token.starts_with("%5B%22strand%22");
            domains+=token.starts_with("%5B%22domain%22");
        }
        clusterLabel=std::to_string(clusters)+" clusters / "+std::to_string(strands)+" strands / "+std::to_string(domains)+" domains";
    }
    void enter(std::array<SidebarMenu,2>& menus) {
        if(!active)savedOffset=menus[1].offset();
        renderedState_.reset();
        active=true;menus[1].open=true;menus[1].offsets[menus[1].selected]=0;menus[1].focus.reset();
    }
    void reset() {for(auto& w:wheels)w.reset();manual=false;defaultPlanes=false;clustersOpen=false;planeHover.fill(std::nullopt);beamEnd.fill(std::nullopt);posed=false;grabbed=1;hand.reset();planeHand.reset();wheelHand.reset();wheel.reset();lastPick.clear();}
    void exit(std::array<SidebarMenu,2>& menus) {
        active=false;reset();pickSlot.reset();
        auto& m=menus[1];m.customTab.reset();m.offsets[m.selected]=savedOffset;m.focus.reset();
    }
    void refresh(std::array<SidebarMenu,2>& menus,const ToolConfigurationDraft& config,const std::string& status) const {
        if(!active)return;
        menus[1].open=true;menus[1].offsets[menus[1].selected]=0;
        const std::string key=twist?"twist":"bend";
        const RenderState state{twist,elements,manual,clustersOpen,selecting,clusterPage,clusterLabel+config.targetSelectionKind(),clusters,config.planeABp(),config.planeBBp(),
            config.bendAngleDegrees(),config.bendDirectionDegrees(),config.twistAmount(),config.twistAmountMode()};
        // Refresh runs every frame (and again while dragging). Retain the menu
        // rows until their inputs change; opening and scrolling still work.
        if(renderedState_==state && renderedStatus_==status && menus[1].customTab && menus[1].customTab->key==key)return;
        renderedState_=state;renderedStatus_=status;
        SidebarTab tab{1,key,twist?"Twist":"Bend",{}};
        auto row=[&](std::string id,std::string label,std::string detail="") {
            tab.rows.push_back({key+":"+id,label,detail,key+":"+id,{}});
        };
        row("back",(twist?"Twist":"Bend")+std::string(" - Return to tools"),clusterLabel+" | "+status);row("confirm","CONFIRM","CYAN POINTS: APPROXIMATE PREVIEW");row("cancel","CANCEL");
        auto bp=[](auto v){return v?std::to_string(*v):std::string("--");};
        row("plane1","Plane 1: "+bp(config.planeABp()),twist?"TRIGGER HOLD NEAREST ELEMENT / BP":"BP INDEX / GRAB PLANE TO MOVE");
        row("plane2","Plane 2: "+bp(config.planeBBp()),twist?"TRIGGER HOLD NEAREST ELEMENT / BP":"BP INDEX / GRAB PLANE TO MOVE");
        if(twist) {
            const bool total=config.twistAmountMode()==TwistAmountMode::total_degrees;
            std::ostringstream amount;amount<<std::fixed<<std::setprecision(total?1:3)<<config.twistAmount();
            row("amount","Amount: "+amount.str()+(total?" deg":" deg/nm"),total?"DRAG THUMBWHEEL / 1 DEG":"DRAG THUMBWHEEL / 0.1 DEG/NM");
            row("less",total?"-5 deg":"-0.5 deg/nm");row("more",total?"+5 deg":"+0.5 deg/nm");
            row("units",total?"Units: total degrees":"Units: degrees / nm","SWITCH UNITS / PRESERVE TOTAL TWIST");
            row("reverse","Reverse direction");row("zero",selecting?"Clear selection":"Zero twist");
            row("target",selecting?"Use selection / Pick planes":"Change selection",clusterLabel);
            row("undo","UNDO");row("recenter","Frame model");
            menus[1].customTab=std::move(tab);return;
        }
        row("cluster",selecting?"Use selection / Pick planes":"Change selection",clusterLabel);
        if(clustersOpen) {
            for(size_t i=clusterPage;i<std::min(clusterPage+4,clusters.size());++i)
                row("cluster-"+std::to_string(i),clusters[i]);
            row("clusters-prev","Previous");row("clusters-next","Next");
        }
        const bool shared=config.targetSelectionKind()!="cluster" && config.targetSelectionKind()!="end";
        row("manual",selecting?"Clear selection":manual?"Manual bend: ON":shared?"Shape handle":"Manual bend",
            selecting?"FILTER: CLUSTER / STRAND / DOMAIN":shared?"PLANE 1 FIXED / SHARED CURVATURE":"KEEP BP INDICES / MOVE PLANE");
        row("angle-wheel", "");row("direction-wheel", "");row("radius-wheel", "");
        row("angle","Angle: "+std::to_string(int(std::round(config.bendAngleDegrees())))+" deg","CYAN POINTS: APPROXIMATE PREVIEW");
        row("direction","Direction: "+std::to_string(int(std::round(config.bendDirectionDegrees())))+" deg","DRAG THUMBWHEEL / 1 DEG");
        row("direction-less","-5 deg");row("direction-more","+5 deg");
        std::ostringstream radius;
        if(config.bendAngleDegrees()>0 && config.planeABp() && config.planeBBp())
            radius<<std::fixed<<std::setprecision(2)<<(*config.planeBBp()-*config.planeABp())*.334/(glm::radians(config.bendAngleDegrees()));
        else radius<<"infinite";
        row("radius","Curvature R: "+radius.str()+" nm","DRAG THUMBWHEEL / 1 DEG ARC STEPS");
        row("radius-less","-10 nm");row("radius-more","+10 nm");
        row("target",elements?"Targets: element ends":"Targets: clusters","TRIGGER TO SWITCH TARGET TYPE");
        row("undo","UNDO");row("recenter","Frame model");
        menus[1].customTab=std::move(tab);
    }
 private:
    using RenderState=std::tuple<bool,bool,bool,bool,bool,size_t,std::string,std::vector<std::string>,std::optional<int32_t>,std::optional<int32_t>,double,double,double,TwistAmountMode>;
    mutable std::optional<RenderState> renderedState_;
    mutable std::string renderedStatus_;
};
}
