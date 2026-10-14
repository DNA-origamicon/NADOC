#define NADOC_SCRYWRITE_TESTING
#define main nadoc_viewer_entry_point
#include "../src/main.cpp"
#undef main
#include <cassert>
namespace {
struct LiveViewerTest {
    static void renderPanel(Viewer& v,const std::string& directory) {
        for(auto& wheel:v.movePanel_.wheels)wheel.reset();
        auto checked=std::make_shared<nadoc_vr::JoinFeedback>();checked->sequence=5;checked->toolSequence=v.toolSequence_;
        checked->requestSequence=v.transformSequence_;checked->status="valid";checked->valid=true;checked->connections=1;
        assert(v.joinPreview_.accept(checked,v.toolSequence_,v.transformSequence_));
        v.sidebarMenus_.menus[1].available=[&](const std::string& action){return v.joinActionAvailable(action);};
        v.refreshJoin();v.movePanel_.refresh(v.sidebarMenus_.menus,v.selectedSelectionKind_,v.toolShell_.status());
        v.sidebarMenus_.initialize();v.sidebarMenus_.draw();v.drawMoveWheels();
        auto& menu=v.sidebarMenus_.menus[1];
        assert(menu.audit.valid());
        GLuint fbo=0,texture=0;glGenFramebuffers(1,&fbo);glBindFramebuffer(GL_FRAMEBUFFER,fbo);
        glGenTextures(1,&texture);glBindTexture(GL_TEXTURE_2D,texture);
        glTexImage2D(GL_TEXTURE_2D,0,GL_RGB8,800,1000,0,GL_RGB,GL_UNSIGNED_BYTE,nullptr);
        glFramebufferTexture2D(GL_FRAMEBUFFER,GL_COLOR_ATTACHMENT0,GL_TEXTURE_2D,texture,0);
        assert(glCheckFramebufferStatus(GL_FRAMEBUFFER)==GL_FRAMEBUFFER_COMPLETE);glDisable(GL_DEPTH_TEST);
        const auto center=menu.placement.worldPoint({0,0,0});
        const auto eye=menu.placement.worldPoint({.10F,0,2});
        const auto up=glm::normalize(menu.placement.worldPoint({0,1,0})-center);
        const auto vp=glm::ortho(-.36F,.36F,-.45F,.45F,.01F,10.F)*glm::lookAt(eye,center,up);
        auto render=[&](glm::mat4 matrix) {
            glViewport(0,0,800,1000);glClearColor(.025F,.03F,.04F,1);glClear(GL_COLOR_BUFFER_BIT);
            v.sidebarMenus_.render(matrix);v.solidWheels_.render(matrix);
            std::vector<unsigned char> pixels(800*1000*3);glReadPixels(0,0,800,1000,GL_RGB,GL_UNSIGNED_BYTE,pixels.data());return pixels;
        };
        const auto pixels=render(vp),hidden=render(vp*glm::translate(glm::mat4(1),glm::vec3(10,0,0)));
        auto green=[](const auto& p){size_t n=0;for(size_t i=0;i<p.size();i+=3)n+=p[i+1]>90 && p[i+1]>p[i]*1.5F && p[i+1]>p[i+2]*1.15F;return n;};
        assert(green(pixels)>500 && green(hidden)==0);
        std::ofstream out(directory+"/join-panel.ppm",std::ios::binary);out<<"P6\n800 1000\n255\n";
        for(int y=999;y>=0;--y)out.write(reinterpret_cast<const char*>(pixels.data()+y*800*3),800*3);
        glBindFramebuffer(GL_FRAMEBUFFER,0);glDeleteFramebuffers(1,&fbo);glDeleteTextures(1,&texture);
        v.sidebarMenus_.shutdown();
    }
    static void renderConnections(Viewer& v,const std::string& directory) {
        v.joinPreview_.clear();
        const auto sites=std::make_shared<nadoc_vr::JoinSiteIndex>();
        sites->add({false,{0,0,0},{1,0,0}});sites->add({true,{1,0,0},{-1,0,0}});
        v.joinPreview_.sites=sites;v.joinPreview_.update(glm::mat4(1));assert(v.joinPreview_.hintCount==1);
        GLuint fbo=0,texture=0;glGenFramebuffers(1,&fbo);glBindFramebuffer(GL_FRAMEBUFFER,fbo);
        glGenTextures(1,&texture);glBindTexture(GL_TEXTURE_2D,texture);
        glTexImage2D(GL_TEXTURE_2D,0,GL_RGB8,400,300,0,GL_RGB,GL_UNSIGNED_BYTE,nullptr);
        glFramebufferTexture2D(GL_FRAMEBUFFER,GL_COLOR_ATTACHMENT0,GL_TEXTURE_2D,texture,0);
        assert(glCheckFramebufferStatus(GL_FRAMEBUFFER)==GL_FRAMEBUFFER_COMPLETE);
        const auto vp=glm::ortho(-.01F,.04F,-.02F,.02F,.01F,5.F);
        auto render=[&] {
            std::vector<Vertex> lines;
            v.drawJoin([&](glm::vec3 a,glm::vec3 b,glm::vec3 color){lines.push_back({a,color,1});lines.push_back({b,color,1});});
            glViewport(0,0,400,300);glClearColor(0,0,0,1);glClear(GL_COLOR_BUFFER_BIT);
            v.glScene_->renderGuides(vp,lines,nullptr,4.F,false,false);
            std::vector<unsigned char> pixels(400*300*3);glReadPixels(0,0,400,300,GL_RGB,GL_UNSIGNED_BYTE,pixels.data());return pixels;
        };
        auto lit=[](const auto& pixels){size_t count=0;for(auto value:pixels)count+=value>100;return count;};
        const auto first=render();assert(lit(first)>100);
        v.joinPreview_.update(glm::translate(glm::mat4(1),glm::vec3(1,0,0)));
        const auto moved=render();assert(lit(moved)>lit(first) && first!=moved);
        v.joinPreview_.update(glm::translate(glm::mat4(1),glm::vec3(5,0,0)));
        assert(lit(render())==0); // Negative control: beyond reach removes visible hints.
        std::ofstream out(directory+"/join-connections.ppm",std::ios::binary);out<<"P6\n400 300\n255\n";
        for(int y=299;y>=0;--y)out.write(reinterpret_cast<const char*>(moved.data()+y*400*3),400*3);
        v.joinPreview_.clear();glBindFramebuffer(GL_FRAMEBUFFER,0);glDeleteFramebuffers(1,&fbo);glDeleteTextures(1,&texture);
    }
    static void checkToolTransitions(Viewer& v) {
        for(size_t edit:{0U,1U}) {
            v.activateEditTool(edit);
            assert(edit==0?v.ligation_.active:v.ligation_.nickActive);
            v.ligation_.hand=1;v.ligation_.target=0;v.ligation_.nickHover[1]=0;
            v.activateSidebarAction("tool:join",1);
            assert(!v.ligation_.active && !v.ligation_.nickActive && !v.ligation_.hand && !v.ligation_.target && !v.ligation_.nickHover[1]);
            assert(v.movePanel_.joining && v.selectionLevel_=="cluster");
        }
        for(const auto tool:{"tool:bend","tool:twist"}) {
            v.activateSidebarAction(tool,1);assert(v.bendPanel_.active);
            v.planeGuides_[0].emplace();v.planeGuides_[1].emplace();
            v.activePlanePickSequence_=7;v.planePickSlot_="a";v.planePickIdentity_="nuc:test";
            v.bendPickExtent_="body";v.bendPanel_.hand=1;
            v.activateSidebarAction("tool:join",1);
            assert(!v.bendPanel_.active && !v.bendPanel_.hand && !v.planeGuides_[0] && !v.planeGuides_[1]);
            assert(!v.activePlanePickSequence_ && !v.planePickSlot_ && v.planePickIdentity_.empty() && !v.bendPickExtent_);
            assert(!v.toolConfig_.active() && v.movePanel_.joining && v.selectionLevel_=="cluster");
        }
    }
    static void run(const std::string& directory) {
        Viewer v(SceneData{},directory+"/events.json");
        v.liveSocket_.open(directory+"/test.sock");
        v.liveMode_="transactions"; // Synthetic controllers; no physical haptic session.
        SceneData data;data.available.fill(true);
        RepresentationData source;ColorSet colors;
        for(auto& color:colors.values)color={.3F,.6F,.9F};
        const glm::vec3 center{0,0,-1.3F};
        source.points.push_back({"nuc:test",center,colors,.02F});
        source.ownerHandles.push_back({"owner",center});
        source.toolScopeOwnership={{"nuc:test",{{"owner",1,1}}}};
        for(auto& rep:data.representations)rep=source;
        v.glScene_=std::make_unique<GlScene>(std::move(data));
        v.selectedIdentity_="nuc:test";v.selectedSelectionKind_="cluster";v.selectedOwnerTokens_={"owner","parent-domain","parent-strand"};
        checkToolTransitions(v);
        v.activateSidebarAction("tool:join",1);
        assert(v.movePanel_.active && v.movePanel_.joining && v.selectionLevel_=="cluster" && v.movePanel_.selecting);
        v.publishSelectionLevel("base");assert(v.selectionLevel_=="cluster");
        const auto reachSequence=v.transformSequence_;
        v.activateSidebarAction("join:reach:more",1);
        assert(std::abs(v.movePanel_.joinReachNm-3.1F)<1e-5F && v.transformSequence_>reachSequence);
        v.activateSidebarAction("join:reach:less",1);assert(v.movePanel_.joinReachNm==3.F);
        // Full cluster selection is acknowledged through the canonical feedback reader.
        v.feedbackPath_=directory+"/selection.feedback";
        v.publishSelect({"nuc:test"});
        {std::ofstream out(v.feedbackPath_);out<<"NADOCVR_FEEDBACK 3 "<<v.selectSequence_<<" 1 1 cluster cluster nuc:test 1 owner\n";}
        v.feedbackPollFrame_=2;v.pollSelectionFeedback();assert(!v.movePanel_.selecting);
        v.sessionState_=XR_SESSION_STATE_FOCUSED;v.normalizationScale_=.01F;
        for(auto& hand:v.hands_){hand.valid=true;hand.position=center;}
        std::array<bool,2> blocked{};
        v.triggerClicked_[0]=v.triggerPressed_[0]=true;
        v.processMoveInput(blocked,false);
        assert(!v.movePanel_.hand && !v.movePanel_.nearby[0] && !blocked[0]);
        v.triggerClicked_[0]=v.triggerPressed_[0]=false;
        // Both acquisition spheres cover geometry. Only the left may hover it.
        for(size_t h=0;h<2;++h) {
            v.hands_[h].position+=center-v.selectionVolumeCenter(h);
            v.triggerPartial_[h]=true;
        }
        v.updateSelectionVolumeCandidates(blocked);
        assert(!v.snapSelectionHits_[0].empty() && v.snapSelectionHits_[1].empty());
        v.hands_[1].position=center+glm::vec3(0,0,.5F);
        v.hands_[1].orientation=glm::angleAxis(glm::half_pi<float>(),glm::vec3(0,1,0));
        v.processMoveInput(blocked,false);assert(!v.movePanel_.beamEnd && !v.movePanel_.nearby[1]);
        v.hands_[1].orientation=glm::quat(1,0,0,0);
        v.triggerClicked_[1]=v.triggerPressed_[1]=true;
        v.processMoveInput(blocked,false);
        assert(v.movePanel_.hand==1 && blocked[1] && v.movePanel_.beamEnd);
        v.updateSelectionVolumeCandidates(blocked);
        assert(v.snapSelectionHits_[0].empty() && v.snapSelectionHits_[1].empty());
        v.triggerClicked_[1]=false;
        v.hands_[1].position.x+=.05F;blocked.fill(false);v.processMoveInput(blocked,false);
        assert(std::abs(v.pendingToolTransform_.transform()[3].x-.05F)<1e-5F);
        // Left-hand movement cannot change the active transform.
        const auto transform=v.pendingToolTransform_.transform();
        v.hands_[0].position.x+=.2F;blocked.fill(false);v.processMoveInput(blocked,false);
        assert(v.pendingToolTransform_.transform()==transform);
        // Release retains the draft, and a second grab starts at the preview.
        v.triggerPressed_[1]=false;v.processMoveInput(blocked,false);
        assert(!v.movePanel_.hand && v.toolShell_.previewRequested() && !v.toolShell_.executionPending());
        blocked.fill(false);v.processMoveInput(blocked,false);assert(v.movePanel_.nearby[1]);
        v.gripClicked_[1]=v.gripPressed_[1]=true;
        v.processMoveGrip(blocked);assert(v.movePanel_.hand && v.movePanel_.rotating && blocked[1]);
        v.movePanel_.snap=true;v.gripClicked_[1]=false;
        v.hands_[1].orientation=glm::angleAxis(glm::radians(22.F),glm::vec3(0,0,1));
        v.processMoveInput(blocked,true);
        assert(std::abs(v.movePanel_.rotationDegrees.z-15)<1e-4F);
        assert(std::abs(v.movePanel_.positionNm.x-5)<1e-4F);
        v.gripPressed_[1]=false;v.processMoveInput(blocked,true);assert(!v.movePanel_.hand);
        v.activateSidebarAction("join:0:more",1);assert(std::abs(v.movePanel_.positionNm.x-6)<1e-4F);
        v.activateSidebarAction("join:5:less",1);assert(std::abs(v.movePanel_.rotationDegrees.z)<1e-4F);
        // Production wheel input uses ray contact and retains exact one-nm detents.
        auto& menu=v.sidebarMenus_.menus[1];menu.placement.openDocked({0,0,0},glm::quat(1,0,0,0));
        auto controls=menu.controls();
        auto wheel=std::find_if(controls.begin(),controls.end(),[](auto c){return c.id=="join:1-wheel";});
        assert(wheel!=controls.end());
        const auto wheelCenter=(wheel->bounds.minimum+wheel->bounds.maximum)*.5F;
        auto aimWheel=[&](float offset) {
            v.hands_[1].position=menu.placement.worldPoint({wheelCenter.x,wheelCenter.y+offset,.4F});
            v.hands_[1].orientation=menu.placement.orientation();
        };
        aimWheel(0);v.triggerClicked_[1]=v.triggerPressed_[1]=true;blocked.fill(false);
        v.processMoveWheels(blocked);assert(v.movePanel_.wheelHand==1);
        v.triggerClicked_[1]=false;aimWheel(.041F);v.frameDeltaSeconds_=.5F;
        blocked.fill(false);v.processMoveWheels(blocked);assert(v.movePanel_.positionNm.y==1);
        v.triggerPressed_[1]=false;v.processMoveWheels(blocked);assert(!v.movePanel_.wheelHand);
        renderPanel(v,directory);renderConnections(v,directory);
        v.activateSidebarAction("join:cancel",1);
        assert(v.pendingToolTransform_.isIdentity() && !v.toolShell_.previewRequested());
        assert(v.movePanel_.positionNm==glm::vec3(0) && v.movePanel_.rotationDegrees==glm::vec3(0));
        // Apply requires matching browser validation, even with an unchanged pose.
        v.movePanel_.selecting=false;v.activateSidebarAction("join:0:more",1);v.activateSidebarAction("join:apply",1);
        assert(!v.toolShell_.executionPending());
        auto checked=std::make_shared<nadoc_vr::JoinFeedback>();checked->sequence=10;checked->toolSequence=v.toolSequence_;
        checked->requestSequence=v.transformSequence_;checked->status="valid";checked->valid=true;checked->connections=1;
        assert(v.joinPreview_.accept(checked,v.toolSequence_,v.transformSequence_));assert(v.joinReady());
        v.activateSidebarAction("join:apply",1);assert(v.toolShell_.executionPending());
        nadoc_vr::ToolExecutionFeedback feedback;feedback.mode="join";feedback.action="confirm";feedback.status="succeeded";
        v.toolShell_.applyExecutionFeedback(feedback);v.moveAwaitRefresh_=false;
        v.ligation_.version=1;v.activateSidebarAction("join:undo",1);
        assert(v.ligation_.waiting && v.ligation_.committedAction=="undo");
        v.ligation_.waiting=false;v.activateSidebarAction("join:redo",1);
        assert(v.ligation_.waiting && v.ligation_.committedAction=="redo");v.ligation_.waiting=false;
        v.activateSidebarAction("join:selection",1);assert(v.movePanel_.selectionEnabled(1));
        v.movePanel_.selecting=false;
        v.hands_[1].orientation=glm::quat(1,0,0,0);v.hands_[1].position=center+glm::vec3(0,0,.5F);
        v.triggerClicked_[1]=v.triggerPressed_[1]=true;blocked.fill(false);v.processMoveInput(blocked,false);
        assert(v.movePanel_.hand);
        v.hands_[1].valid=false;v.processMoveInput(blocked,false);assert(!v.movePanel_.hand);
        blocked.fill(false);v.processMoveInput(blocked,false); // Next frame clears the cancelled preview.
        v.movePanel_.exit(v.sidebarMenus_.menus);
        v.hands_[1].valid=true;v.hands_[1].position=center;
        v.hands_[1].position+=center-v.selectionVolumeCenter(1);
        blocked.fill(false);v.updateSelectionVolumeCandidates(blocked);
        assert(!v.snapSelectionHits_[1].empty());
    }
};
}
int main(int argc,char** argv) {
    if(argc!=2)return 2;
    std::filesystem::create_directories(argv[1]);
    std::filesystem::permissions(argv[1],std::filesystem::perms::owner_all);
    if(!glfwInit())return 77;
    glfwWindowHint(GLFW_VISIBLE,GLFW_FALSE);
    glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR,4);glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR,3);
    auto* window=glfwCreateWindow(128,128,"Join hand roles",nullptr,nullptr);
    if(!window)return 77;
    glfwMakeContextCurrent(window);LiveViewerTest::run(argv[1]);
    glfwDestroyWindow(window);glfwTerminate();
}
