#define NADOC_SCRYWRITE_TESTING
#define main nadoc_viewer_entry_point
#include "../src/main.cpp"
#undef main
#include <cassert>
namespace {
struct LiveViewerTest {
    static void renderPanel(Viewer& v,const std::string& directory) {
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
        std::ofstream out(directory+"/move-panel.ppm",std::ios::binary);out<<"P6\n800 1000\n255\n";
        for(int y=999;y>=0;--y)out.write(reinterpret_cast<const char*>(pixels.data()+y*800*3),800*3);
        glBindFramebuffer(GL_FRAMEBUFFER,0);glDeleteFramebuffers(1,&fbo);glDeleteTextures(1,&texture);
        v.sidebarMenus_.shutdown();
    }
    static void run(const std::string& directory) {
        Viewer v(SceneData{},directory+"/events.json");
        v.liveSocket_.open(directory+"/test.sock");
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
        v.activateSidebarAction("tool:move_rotate",1);
        assert(v.movePanel_.active);
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
        v.activateSidebarAction("move:0:more",1);assert(std::abs(v.movePanel_.positionNm.x-6)<1e-4F);
        v.activateSidebarAction("move:5:less",1);assert(std::abs(v.movePanel_.rotationDegrees.z-14)<1e-4F);
        // Production wheel input uses ray contact and retains exact one-nm detents.
        auto& menu=v.sidebarMenus_.menus[1];menu.placement.openDocked({0,0,0},glm::quat(1,0,0,0));
        auto controls=menu.controls();
        auto wheel=std::find_if(controls.begin(),controls.end(),[](auto c){return c.id=="move:1-wheel";});
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
        renderPanel(v,directory);
        v.activateSidebarAction("move:cancel",1);
        assert(v.pendingToolTransform_.isIdentity() && !v.toolShell_.previewRequested());
        assert(v.movePanel_.positionNm==glm::vec3(0) && v.movePanel_.rotationDegrees==glm::vec3(0));
        v.activateSidebarAction("move:0:more",1);v.activateSidebarAction("move:apply",1);
        assert(v.toolShell_.executionPending());
        nadoc_vr::ToolExecutionFeedback feedback;feedback.mode="move_rotate";feedback.action="confirm";feedback.status="succeeded";
        v.toolShell_.applyExecutionFeedback(feedback);v.moveAwaitRefresh_=false;
        v.ligation_.version=1;v.activateSidebarAction("move:undo",1);
        assert(v.ligation_.waiting && v.ligation_.committedAction=="undo");
        v.ligation_.waiting=false;v.activateSidebarAction("move:redo",1);
        assert(v.ligation_.waiting && v.ligation_.committedAction=="redo");v.ligation_.waiting=false;
        v.activateSidebarAction("move:selection",1);assert(v.movePanel_.selectionEnabled(1));
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
    auto* window=glfwCreateWindow(128,128,"Move hand roles",nullptr,nullptr);
    if(!window)return 77;
    glfwMakeContextCurrent(window);LiveViewerTest::run(argv[1]);
    glfwDestroyWindow(window);glfwTerminate();
}
