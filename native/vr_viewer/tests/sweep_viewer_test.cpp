// Production Sweep input, feature acknowledgements, panel and GL preview evidence.
#define NADOC_SCRYWRITE_TESTING
#define main nadoc_viewer_entry_point
#include "../src/main.cpp"
#undef main
#include <cassert>

namespace {
struct LiveViewerTest {
    static std::vector<Vertex> guides(Viewer& v) {
        std::vector<Vertex> lines;
        v.drawSweep([&](glm::vec3 a,glm::vec3 b,glm::vec3 c){lines.push_back({a,c,1});lines.push_back({b,c,1});});
        v.drawSweepWarnings([&](glm::vec3 a,glm::vec3 b,glm::vec3 c){lines.push_back({a,c,1});lines.push_back({b,c,1});});
        return lines;
    }
    static void save(const std::string& path,const std::vector<unsigned char>& rgb,int width,int height) {
        std::ofstream image(path,std::ios::binary);image<<"P6\n"<<width<<' '<<height<<"\n255\n";
        for(int y=height-1;y>=0;--y)image.write(reinterpret_cast<const char*>(rgb.data()+y*width*3),width*3);
    }
    static void renderPath(Viewer& v,const std::string& path,bool warning=false) {
        // Diagnostic camera faces the path from its side; the model/inputs stay fixed.
        auto lines=guides(v);assert(lines.size()>20);
        glm::vec3 low(1e6F),high(-1e6F);
        for(const auto& vertex:lines){low=glm::min(low,vertex.position);high=glm::max(high,vertex.position);}
        const auto center=(low+high)*.5F;
        const auto eye=center+glm::vec3(0,-2,0);
        v.witnessObserverOrientation_=glm::quat_cast(glm::inverse(glm::lookAt(eye,center,glm::vec3(0,0,1))));
        lines=guides(v);
        const float radius=std::max(high.x-low.x,high.z-low.z)*.5F+.055F;
        const auto vp=glm::ortho(-radius,radius,-radius,radius,.01F,10.F)*glm::lookAt(eye,center,glm::vec3(0,0,1));
        auto render=[&](const std::vector<Vertex>& vertices) {
            glViewport(0,0,600,600);glClearColor(.015F,.02F,.025F,1);
            glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT);
            v.glScene_->renderGuides(vp,vertices);
            std::vector<unsigned char> pixels(600*600*3);
            glReadPixels(0,0,600,600,GL_RGB,GL_UNSIGNED_BYTE,pixels.data());return pixels;
        };
        const auto pixels=render(lines);
        save(path,pixels,600,600);
        size_t green=0;for(size_t i=0;i<pixels.size();i+=3)
            if(pixels[i+1]>120 && pixels[i+1]>pixels[i]*1.25F && pixels[i+1]>pixels[i+2]*1.15F)++green;
        std::cerr<<"Sweep render lines="<<lines.size()<<" green="<<green<<" gl_error="<<glGetError()<<" radius="<<radius<<std::endl;
        assert(green>120);
        // Require color near the actual curve midpoint, not merely panel/marker ink.
        const auto& pathPoints=v.sweepDraft_.drawing?v.sweepDraft_.strokeNm:v.sweepCurve_;
        const auto middle=v.sweepWorldPoint(pathPoints[pathPoints.size()/2]);
        const auto clip=vp*glm::vec4(middle,1);
        const auto point=glm::ivec2((clip.x/clip.w+1)*300,(clip.y/clip.w+1)*300);
        int localGreen=0;
        for(int y=std::max(0,point.y-8);y<std::min(600,point.y+9);++y)
            for(int x=std::max(0,point.x-8);x<std::min(600,point.x+9);++x) {
                const auto i=(y*600+x)*3;if(pixels[i+1]>120 && pixels[i+1]>pixels[i]*1.25F)++localGreen;
            }
        if(warning) {
            size_t orange=0;
            for(size_t i=0;i<pixels.size();i+=3)if(pixels[i]>180 && pixels[i+1]<140 && pixels[i+2]<110)++orange;
            assert(orange>25);
        }else assert(localGreen>0);
        save(path,pixels,600,600);
        const bool active=v.sweepPanel_.active;v.sweepPanel_.active=false;
        assert(guides(v).empty());const auto hidden=render(guides(v));v.sweepPanel_.active=active;
        assert(hidden!=pixels);
        for(size_t i=0;i<hidden.size();i+=3)assert(hidden[i+1]<120);
        std::cout<<"Sweep visible green pixels: "<<green<<", midpoint: "<<localGreen<<'\n';
    }
    static void run(const std::string& directory) {
        char socketDirectory[]="/tmp/nadoc-sweep-sockets-XXXXXX";
        assert(::mkdtemp(socketDirectory));
        Viewer v(SceneData{},directory+"/events.json");
        v.liveSocket_.open(std::string(socketDirectory)+"/viewer.sock");
        SceneData empty;empty.available.fill(true);v.glScene_=std::make_unique<GlScene>(std::move(empty));
        v.sidebarMenus_.initialize();v.latticePanelSurface_.initialize();
        v.normalizationScale_=.026F;v.sessionState_=XR_SESSION_STATE_FOCUSED;
        v.extrudePlane_.plane="XY";v.extrudePlane_.lattice="SQUARE";
        v.selectedIdentity_="prior-selected-end";v.selectedSelectionKind_="end";v.selectedOwnerTokens_={"prior-owner"};
        v.activateSidebarAction("tool:sweep",1);
        assert(v.sweepPanel_.active && v.sweepDraft_.step==1 && v.latticeOpen_);
        assert(v.toolShell_.mode()==nadoc_vr::ToolMode::sweep);
        assert(v.toolConfig_.targetSelectionKind()=="none" && v.toolConfig_.targetIdentity().empty());
        std::istringstream occupied("XY 1 3 4");v.latticeContext_.readOccupancy(occupied);
        assert(v.latticeCellOccupied({3,4}) && !v.latticeCellOccupied({0,0}));
        assert(v.existingLatticeCells().size()==1);
        (void)v.extrudeLatticeDraft_.setSelected({3,4},true);
        v.centerLatticePainting(true);assert(v.extrudeLatticeDraft_.cells().empty());
        assert(!v.thumbwheelAvailable());
        v.activateSidebarAction("sweep:confirm",1);assert(v.sweepDraft_.step==1);
        (void)v.extrudeLatticeDraft_.setSelected({0,0},true);
        (void)v.extrudeLatticeDraft_.setSelected({0,1},true);v.publishSweepDraft();
        v.activateSidebarAction("sweep:confirm",1);
        assert(v.sweepDraft_.step==2 && !v.latticeOpen_ && v.sweepDraft_.pointsNm.size()==2);
        auto& panel=v.sidebarMenus_.menus[1];
        assert(panel.sweepPath());
        assert(!v.sweepReady());
        // Radial Delete Last preserves an earlier selected point (including origin).
        const auto initialPoints=v.sweepDraft_.pointsNm;
        v.activateRadialEdit(1);assert(v.sweepDraft_.pointsNm.size()==3);
        v.activateSidebarAction("sweep:point:1",1);
        v.activateRadialEdit(0);assert(v.sweepDraft_.pointsNm==initialPoints && v.sweepDraft_.selected==1);
        v.activateRadialEdit(1);v.activateSidebarAction("sweep:point:0",1);
        assert(v.sweepActionAvailable("sweep:delete-last-point"));
        v.activateRadialEdit(0);assert(v.sweepDraft_.pointsNm==initialPoints && v.sweepDraft_.selected==0);
        // The list's explicitly labelled Delete Selected button still edits its selection.
        v.activateRadialEdit(1);v.activateSidebarAction("sweep:point:1",1);
        const auto endpoint=v.sweepDraft_.pointsNm.back();
        v.activateSidebarAction("sweep:delete-point",1);
        assert(v.sweepDraft_.pointsNm.size()==2 && v.sweepDraft_.pointsNm[1]==endpoint);
        v.sweepDraft_.movePoint(1,initialPoints[1]);v.publishSweepDraft();
        v.activateSidebarAction("sweep:axis:1:0:1",1);
        assert(v.sweepDraft_.pointsNm[1].x==1);
        v.activateSidebarAction("sweep:axis:0:0:1",1);
        assert(v.sweepDraft_.pointsNm[0]==glm::vec3(0));
        std::array<bool,2> blocked{};
        auto process=[&] {blocked.fill(false);v.processSweepInput(blocked,false);};
        v.hands_[1].valid=true;v.hands_[1].orientation=glm::quat(1,0,0,0);
        v.hands_[1].position=v.sweepWorldPoint(v.sweepDraft_.pointsNm[1])+glm::vec3(0,0,.25F);
        process();assert(v.sweepHovered_[1]==1);
        const auto hoveredGuides=guides(v);
        assert(std::any_of(hoveredGuides.begin(),hoveredGuides.end(),[&](const auto& vertex){
            return glm::distance(vertex.position,v.hands_[1].position)<1e-6F;
        }));
        v.triggerClicked_[1]=true;v.triggerPressed_[1]=true;process();
        assert(v.sweepHand_==1 && v.sweepDraft_.selected==1);
        blocked.fill(true);v.processSweepInput(blocked,false);
        assert(v.sweepHand_==1); // Hovering a menu during a held point drag keeps ownership.
        v.triggerClicked_[1]=false;v.hands_[1].position.x+=.078F;process();
        assert(std::abs(v.sweepDraft_.pointsNm[1].x-4)<1e-4F);
        v.triggerPressed_[1]=false;process();assert(!v.sweepHand_);
        v.triggerClicked_[1]=true;v.triggerPressed_[1]=true;process();assert(v.sweepHand_==1);
        v.suspendControllerInput();assert(!v.sweepHand_ && !v.sweepDraft_.drawing);
        v.hands_[1].valid=true;v.hands_[1].orientation=glm::quat(1,0,0,0);
        v.hands_[1].position.x+=10;process();assert(!v.sweepHovered_[1]);
        // Canonical model-space points round-trip despite export rotation and framing.
        const auto originalAxes=v.sourceAxes_;
        for(const auto basis:{glm::mat3(1),glm::mat3_cast(glm::quat(glm::vec3(.4F,-.7F,1.1F)))}) {
            v.sourceAxes_=basis;
            for(const auto p:{glm::vec3(0),glm::vec3(4,-3,12)}) {
                assert(glm::distance(v.sweepRelativePoint(v.sweepWorldPoint(p)),p)<1e-4F);
                const auto expected=glm::vec3(v.manipulator_.transform()*glm::vec4(basis*p*v.normalizationScale_,0));
                assert(glm::distance(v.sweepWorldPoint(p)-v.sweepWorldPoint({}),expected)<1e-5F);
            }
        }
        v.sourceAxes_=originalAxes;
        // Grips rotate the point frame without moving it or granting scene grip ownership.
        v.hands_[1].valid=true;v.hands_[1].orientation=glm::quat(1,0,0,0);
        v.hands_[1].position=v.sweepWorldPoint(v.sweepDraft_.pointsNm[1])+glm::vec3(0,0,.25F);
        const auto fixedPoints=v.sweepDraft_.pointsNm;
        v.gripClicked_[1]=v.gripPressed_[1]=true;blocked.fill(false);v.processSweepGrip(blocked);
        assert(blocked[1] && v.sweepGripHand_==1 && v.suppressManipulationUntilRelease_);
        assert(v.sweepDraft_.directionControlled(1));
        const auto oldAngles=*v.sweepDraft_.orientations[1];
        v.gripClicked_[1]=false;
        v.hands_[1].orientation=glm::angleAxis(glm::radians(20.F),glm::vec3(0,1,0));
        blocked.fill(false);v.processSweepGrip(blocked);
        assert(v.sweepDraft_.pointsNm==fixedPoints);
        const auto angles=*v.sweepDraft_.orientations[1];
        assert(glm::length(angles-oldAngles)>10.F);
        for(int axis=0;axis<3;++axis)assert(std::abs(std::remainder(angles[axis],15.F))<1e-5F);
        v.gripPressed_[1]=false;v.processSweepGrip(blocked);assert(!v.sweepGripHand_);
        renderPath(v,directory+"/sweep-point-orientation.ppm");
        v.activateSidebarAction("sweep:direction:1",1);assert(!v.sweepDraft_.directionControlled(1));
        // The fixed origin permits orientation control, but remains position-fixed.
        v.activateSidebarAction("sweep:direction:0",1);assert(v.sweepDraft_.directionControlled(0));
        v.activateSidebarAction("sweep:axis:0:2:1",1);assert(v.sweepDraft_.pointsNm[0]==glm::vec3(0));
        v.activateSidebarAction("sweep:direction:0",1);
        const std::string record="NADOCVR_PREFLIGHT 3 "+std::to_string(v.toolConfigSequence_)+
            " 100 warn sweep none - backend_warning 2 1 1 1 0 0 0 0 0 10 1 0 0 1 0 0 0 1 0 0 0 1 0";
        auto advisory=nadoc_vr::parseToolPreflightFeedback(record,v.toolConfigSequence_);
        assert(advisory && advisory->sweepWarnings==std::vector<size_t>{0});
        auto countedRecord=record;countedRecord.replace(18,1,"4");
        auto counted=nadoc_vr::parseToolPreflightFeedback(countedRecord+" 1234",v.toolConfigSequence_);
        assert(counted && counted->sweepTotalBp==1234);
        v.toolPreflightFeedback_=advisory;assert(v.sweepReady());
        auto warningPoints=v.sweepWarningWorldPoints();assert(warningPoints.size()==1);
        v.hands_[1]={true,false,warningPoints[0]+glm::vec3(0,0,.4F),glm::quat(1,0,0,0)};
        v.triggerClicked_[1]=true;blocked.fill(false);v.processSweepWarnings(blocked);
        assert(blocked[1] && v.sweepWarningTooltip_ && v.sweepWarningTooltipUntil_>glfwGetTime());
        v.triggerClicked_[1]=false;
        const auto warningGuides=guides(v);
        assert(std::any_of(warningGuides.begin(),warningGuides.end(),[](const auto& vertex){return glm::distance(vertex.color,glm::vec3(1,.25F,.12F))<1e-6F;}));
        renderPath(v,directory+"/sweep-curvature-warning.ppm",true);
        v.toolPreflightFeedback_.reset();
        // An invalid tracking sample cannot become valid again through refitting.
        v.activateSidebarAction("sweep:free-draw",1);
        v.hands_[1].position=v.sweepWorldPoint({})+glm::vec3(0,0,.12F);
        v.triggerClicked_[1]=true;v.triggerPressed_[1]=true;process();
        v.triggerClicked_[1]=false;
        v.hands_[1].position=v.sweepWorldPoint({0,0,5})+glm::vec3(0,0,.12F);process();
        v.hands_[1].position=v.sweepWorldPoint({20000,0,5})+glm::vec3(0,0,.12F);process();
        v.triggerPressed_[1]=false;process();
        assert(v.sweepDraft_.strokeInvalid && !v.sweepDraft_.validPath());
        v.activateSidebarAction("sweep:smoothing-more",1);
        assert(!v.sweepDraft_.validPath() && v.sweepDraft_.pointsNm.size()==1);
        v.activateSidebarAction("sweep:free-draw",1);
        v.hands_[1].position=v.sweepWorldPoint({})+glm::vec3(0,0,.12F);
        v.triggerClicked_[1]=true;v.triggerPressed_[1]=true;process();
        v.triggerClicked_[1]=false;
        v.hands_[1].position=v.sweepWorldPoint({0,0,5})+glm::vec3(0,0,.12F);process();
        v.neutralLiveInput(false);
        assert(!v.sweepHand_ && !v.sweepDraft_.drawing && v.sweepDraft_.pointsNm.size()==1);
        assert(!v.sweepDraft_.validPath() && v.sweepDraft_.strokeNm.empty());
        v.activateSidebarAction("sweep:free-draw",1);
        assert(v.sweepDraft_.freeDrawArmed && v.sweepDraft_.pointsNm.size()==1);
        v.hands_[1].position=v.sweepWorldPoint({})+glm::vec3(0,0,.12F);
        v.triggerClicked_[1]=true;v.triggerPressed_[1]=true;process();
        assert(v.sweepDraft_.drawing && v.sweepHand_==1);
        v.triggerClicked_[1]=false;
        for(int i=1;i<=80;++i) {
            const float t=float(i)/80;
            const glm::vec3 p(8*std::sin(t*glm::half_pi<float>()),3*std::sin(t*glm::pi<float>()),18*t);
            v.hands_[1].position=v.sweepWorldPoint(p)+glm::vec3(0,0,.12F);process();
        }
        assert(v.sweepDraft_.strokeNm.size()>10);renderPath(v,directory+"/sweep-free-draw.ppm");
        v.triggerPressed_[1]=false;process();
        assert(!v.sweepHand_ && !v.sweepDraft_.drawing && !v.sweepDraft_.freeDrawArmed);
        assert(v.sweepDraft_.validPath() && v.sweepDraft_.pointsNm.size()<=64);
        assert(v.sweepDraft_.pointsNm.front()==glm::vec3(0));
        assert(glm::distance(v.sweepDraft_.pointsNm.back(),glm::vec3(8,0,18))<1e-3F);
        v.hands_={};v.sweepHovered_={};
        renderPath(v,directory+"/sweep-preview.ppm");
        assert(!v.sweepCloud_.empty() && v.sweepCloud_.size()<=4096);
        v.refreshExtrudePanel();
        panel.placement.openDocked({0,0,0},glm::quat(1,0,0,0));
        panel.placement.setScale(.8F);panel.open=true;
        v.sidebarMenus_.draw();assert(panel.audit.valid());
        const auto vp=glm::ortho(-.52F,.52F,-.57F,.57F,.01F,10.F)*glm::lookAt(glm::vec3(0,0,2),glm::vec3(0),glm::vec3(0,1,0));
        glViewport(0,0,900,900);glClearColor(.02F,.025F,.04F,1);glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT);
        v.renderMenuSurface(vp);
        std::vector<unsigned char> pixels(900*900*3);glReadPixels(0,0,900,900,GL_RGB,GL_UNSIGNED_BYTE,pixels.data());
        save(directory+"/sweep-panel.ppm",pixels,900,900);
        // The event retains native points and paints, and a stale selection cannot retarget it.
        std::ostringstream config;v.writeSweepConfiguration(config);
        assert(config.str().find("\"points_nm\":[[0,0,0]")!=std::string::npos);
        const auto points=v.sweepDraft_.pointsNm;
        auto validate=[&] {
            v.toolPreflightFeedback_=nadoc_vr::ToolPreflightFeedback{
                v.toolConfigSequence_,1,"ok","sweep","none","","validated"};assert(v.sweepReady());
        };
        validate();v.activateSidebarAction("sweep:confirm",1);
        assert(v.toolShell_.executionPending() && v.lastToolTargetKind_=="none" && v.lastToolTargetIdentity_.empty());
        v.refreshExtrudePanel();assert(panel.spinning("sweep:confirm"));
        panel.available=[&](const auto& action){return v.sweepActionAvailable(action);};
        double clock=1.;panel.animationClock=[&]{return clock;};
        auto pendingPixels=[&](const std::string& filename) {
            v.sidebarMenus_.draw();glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT);v.renderMenuSurface(vp);
            std::vector<unsigned char> image(900*900*3);glReadPixels(0,0,900,900,GL_RGB,GL_UNSIGNED_BYTE,image.data());
            save(directory+"/"+filename,image,900,900);return image;
        };
        const auto spinnerA=pendingPixels("sweep-generating-a.ppm");clock+=.23;
        const auto spinnerB=pendingPixels("sweep-generating-b.ppm");assert(spinnerA!=spinnerB);
        size_t greenPixels=0;for(size_t i=0;i<spinnerA.size();i+=3)if(spinnerA[i+1]>90 && spinnerA[i+1]>spinnerA[i]*1.4)++greenPixels;
        assert(greenPixels>100);
        const auto submittedSequence=v.toolSequence_,submittedConfig=v.toolConfigSequence_;
        v.activateSidebarAction("sweep:cancel",1);assert(v.toolSequence_==submittedSequence && v.sweepPanel_.active);
        v.toolExecutionFeedbackPath_=directory+"/execution-feedback.txt";
        auto acknowledge=[&](const std::string& action,const std::string& status,const std::string& feature="-") {
            std::ofstream(v.toolExecutionFeedbackPath_)<<"NADOCVR_TOOL_EXECUTION 1 "<<v.toolExecutionFeedbackSequence_+1
                <<' '<<v.toolSequence_<<" sweep "<<action<<" none - "<<status<<" test_result "<<feature<<'\n';
            v.toolExecutionFeedbackPollFrame_=2;v.pollToolExecutionFeedback();
        };
        acknowledge("confirm","failed");
        assert(!v.toolShell_.executionPending() && v.sweepPanel_.active && v.sweepDraft_.pointsNm==points);
        assert(!panel.spinning("sweep:confirm"));
        assert(v.toolConfigSequence_>submittedConfig && !v.sweepReady());
        validate();v.activateSidebarAction("sweep:confirm",1);acknowledge("confirm","succeeded","sweep-feature");
        assert(!v.sweepPanel_.active && !v.toolConfig_.active() && guides(v).empty());
        assert(v.toolShell_.undoAvailable() && v.committedFeatureLogEntryId_=="sweep-feature");
        v.activateSidebarAction("tool:sweep",1);v.activateSidebarAction("sweep:undo",1);
        assert(v.toolShell_.executionPending());acknowledge("undo","succeeded","sweep-feature");
        assert(!v.toolShell_.undoAvailable() && v.committedFeatureLogEntryId_.empty());
        v.activateSidebarAction("sweep:cancel",1);
        assert(!v.sweepPanel_.active && !v.toolConfig_.active() && v.extrudeLatticeDraft_.cells().empty());
        std::ofstream(directory+"/warning.scene")<<"NADOCVR 16 full strand\nQ empty_authoring\n# SWEEP_WARNING 2 4 6\n";
        auto savedWarning=loadScene(directory+"/warning.scene");assert(savedWarning.sweepWarnings.size()==1);
        v.glScene_=std::make_unique<GlScene>(std::move(savedWarning));
        const auto savedPoints=v.sweepWarningWorldPoints();assert(savedPoints.size()==1);
        v.hands_[1]={true,false,savedPoints[0]+glm::vec3(0,0,.4F),glm::quat(1,0,0,0)};
        v.triggerClicked_[1]=true;blocked.fill(false);v.processSweepWarnings(blocked);
        assert(blocked[1] && v.sweepWarningTooltip_==savedPoints[0]);
        assert(glGetError()==GL_NO_ERROR);
        std::filesystem::remove_all(socketDirectory);
        std::cout<<"Sweep paint/path, radial, point ray/drag, free draw, panel, preview and transaction lifecycle passed\n";
    }
};
}
int main(int argc,char** argv) {
    if(argc!=2)return 2;
    std::filesystem::create_directories(argv[1]);
    std::filesystem::permissions(argv[1],std::filesystem::perms::owner_all);
    if(!glfwInit())return 77;
    glfwWindowHint(GLFW_VISIBLE,GLFW_FALSE);glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR,3);
    glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR,3);glfwWindowHint(GLFW_OPENGL_PROFILE,GLFW_OPENGL_CORE_PROFILE);
    auto* window=glfwCreateWindow(900,900,"Sweep validation",nullptr,nullptr);if(!window)return 77;
    glfwMakeContextCurrent(window);LiveViewerTest::run(std::filesystem::absolute(argv[1]).string());
    glfwDestroyWindow(window);glfwTerminate();
}
