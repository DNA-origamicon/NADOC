// Production painter rendering and hit tests, with an occupied 1 x 8 platform.
#define NADOC_SCRYWRITE_TESTING
#define main nadoc_viewer_entry_point
#include "../src/main.cpp"
#undef main
#include <cassert>
namespace {
struct LiveViewerTest {
    static void run(const std::string& directory) {
        Viewer v(SceneData{},directory+"/events.json");
        v.liveSocket_.open(directory+"/test.sock");
        SceneData data;data.available.fill(true);
        v.glScene_=std::make_unique<GlScene>(std::move(data));
        v.latticePanelSurface_.initialize();v.sidebarMenus_.initialize();
        v.extrudePlane_.plane="XY";v.extrudePlane_.lattice="SQUARE";
        std::istringstream context("XY 0 0 0 1 0 0 0 1 0 0 0 1 8 0 0 0 1 0 2 0 3 0 4 0 5 0 6 0 7");
        v.latticeContext_.read(context);
        v.normalizationScale_=.026F;
        // Semantic/radial entry uses the same sidebar and clears the old tool.
        v.activateAuthoringTool(3);
        assert(v.movePanel_.active);
        v.activateAuthoringTool(0);
        assert(v.extrudePanel_.active && !v.movePanel_.active);
        assert(v.sidebarMenus_.menus[1].tab().key=="extrude");
        v.activateSidebarAction("tool:extrude",1);
        v.latticePlacement_.openDocked({-.42F,0,0},glm::quat(1,0,0,0));
        v.sidebarMenus_.menus[1].placement.openDocked({.30F,0,0},glm::quat(1,0,0,0));
        v.sidebarMenus_.menus[1].placement.setScale(.53F);
        const auto paintedBefore=v.extrudeLatticeDraft_.cells();
        v.latticeOpen_=false; // Length remains usable without the painter.
        assert(v.thumbwheelAvailable());
        auto& sidebar=v.sidebarMenus_.menus[1];
        sidebar.scroll(1);v.refreshExtrudePanel();
        for(bool square:{false,true})for(size_t index=0;index<2;++index)for(int sign:{-1,1}) {
            v.latticeSquare_=square;
            (void)v.toolConfig_.adjustExtrudeLengthBp(56-v.toolConfig_.lengthBp());
            v.frameDeltaSeconds_=.5F;
            v.hands_={};v.triggerClicked_={};v.triggerPressed_={};
            const size_t hand=index; // Either controller can acquire either wheel.
            auto local=nadoc_vr::extrudeWheelFront(index)+glm::vec3(0,0,.3F);
            v.hands_[hand].valid=true;
            v.hands_[hand].position=sidebar.placement.worldPoint(local);
            v.hands_[hand].orientation=sidebar.placement.orientation();
            v.triggerClicked_[hand]=true;v.triggerPressed_[hand]=true;
            assert(v.processThumbwheelInput({})[hand]);
            assert(v.thumbwheelControls_[index].dragging());
            v.triggerClicked_[hand]=false;
            local.y+=sign*nadoc_vr::ThumbwheelControl::kNotchTravel*1.1F;
            v.hands_[hand].position=sidebar.placement.worldPoint(local);
            assert(v.processThumbwheelInput({})[hand]);
            assert(v.toolConfig_.lengthBp()==56+sign*nadoc_vr::extrudeWheelStep(square,index));
            v.triggerPressed_[hand]=false;
            (void)v.processThumbwheelInput({});
            assert(!v.thumbwheelControls_[index].dragging());
            assert(v.extrudeLatticeDraft_.cells()==paintedBefore);
        }
        v.resetThumbwheels();v.hands_={};v.latticeSquare_=true;v.latticeOpen_=true;
        // A nearer painter consumes the pointer; it cannot turn a wheel behind it.
        const auto wheelFront=sidebar.placement.worldPoint(nadoc_vr::extrudeWheelFront(0));
        v.hands_[1].valid=true;v.hands_[1].position=wheelFront+glm::vec3(0,0,.4F);
        v.hands_[1].orientation=glm::quat(1,0,0,0);
        v.triggerClicked_[1]=true;v.triggerPressed_[1]=true;
        v.latticePlacement_.openDocked(wheelFront+glm::vec3(0,0,.2F),glm::quat(1,0,0,0));
        assert(!v.processThumbwheelInput({})[1]);
        assert(!v.thumbwheelHand_);
        v.latticeOpen_=false;
        sidebar.focus.begin("extrude:confirm","");
        assert(!v.processThumbwheelInput({})[1]);
        assert(!v.thumbwheelHand_);
        sidebar.focus.reset();
        assert(v.processThumbwheelInput({})[1]);
        assert(v.thumbwheelControls_[0].dragging());
        v.resetThumbwheels();v.hands_={};v.triggerClicked_={};v.triggerPressed_={};
        sidebar.offsets[sidebar.selected]=0;
        v.activateAuthoringTool(3);
        assert(!v.extrudePanel_.active && !v.thumbwheelAvailable());
        v.activateAuthoringTool(0);
        v.latticePlacement_.openDocked({-.42F,0,0},glm::quat(1,0,0,0));
        auto ray=[&](nadoc_vr::LatticeCell cell) {
            nadoc_vr::HandPose h;h.valid=true;
            h.position=v.latticePlacement_.worldPoint({v.latticeCellPosition(cell),.4F});
            h.orientation=v.latticePlacement_.orientation();return h;
        };
        assert(v.existingLatticeCells().size()==8);
        assert(!v.latticeHit(ray({0,4})));
        assert(v.latticeHit(ray({1,4}))==nadoc_vr::LatticeCell(1,4));
        (void)v.extrudeLatticeDraft_.setSelected({1,4},true);
        (void)v.extrudeLatticeDraft_.setSelected({-2,6},true);
        (void)v.toolConfig_.adjustExtrudeLengthBp(32);
        v.refreshExtrudePanel();v.sidebarMenus_.draw();
        v.appendLatticeGuides();v.appendThumbwheelGuides();
        assert(v.latticeLayoutAudit_.valid());
        assert(v.sidebarMenus_.menus[1].audit.valid());
        const auto projection=glm::ortho(-.80F,.72F,-.54F,.54F,.01F,10.F)*
            glm::lookAt(glm::vec3(0,0,2),glm::vec3(0),glm::vec3(0,1,0));
        auto background=[] {
            glViewport(0,0,1280,900);glDisable(GL_SCISSOR_TEST);
            glClearColor(.015F,.020F,.035F,1);glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT);
            // Fine contrasting stripes make the production frost blur measurable.
            glEnable(GL_SCISSOR_TEST);
            for(int x=0;x<1280;x+=12) {
                glScissor(x,0,6,900);glClearColor(.14F,.22F,.31F,1);glClear(GL_COLOR_BUFFER_BIT);
            }
            glDisable(GL_SCISSOR_TEST);
        };
        auto pixels=[] {
            std::vector<unsigned char> rgb(1280*900*3);
            glReadPixels(0,0,1280,900,GL_RGB,GL_UNSIGNED_BYTE,rgb.data());return rgb;
        };
        background();const auto plain=pixels();
        v.renderMenuSurface(projection);const auto visible=pixels();
        size_t changed=0,selected=0;
        for(size_t i=0;i<visible.size();i+=3) {
            if(std::abs(int(visible[i])-plain[i])>10)++changed;
            if(visible[i]>200 && visible[i+1]>140 && visible[i+2]<130)++selected;
        }
        std::ofstream ppm(directory+"/extrude-panels.ppm",std::ios::binary);
        ppm<<"P6\n1280 900\n255\n";
        for(int y=899;y>=0;--y)ppm.write(reinterpret_cast<const char*>(visible.data()+y*1280*3),1280*3);
        ppm.close();
        std::cout<<"Changed pixels: "<<changed<<" selected pixels: "<<selected<<std::endl;
        assert(changed>100000);
        auto pixel=[&](glm::vec3 local) {
            const auto clip=projection*glm::vec4(v.latticePlacement_.worldPoint(local),1);
            return glm::ivec2((clip.x/clip.w+1)*640,(clip.y/clip.w+1)*450);
        };
        // Require selected-color ink at EACH requested cell, not a whole-image count.
        for(const auto& cell:v.extrudeLatticeDraft_.cells()) {
            const auto p=pixel({v.latticeCellPosition(cell),0});
            const int radius=std::abs(pixel({v.latticeCellPosition(cell)+glm::vec2(v.latticeCellRadius(),0),0}).x-p.x)+2;
            int ink=0;
            for(int y=p.y-radius;y<=p.y+radius;++y)for(int x=p.x-radius;x<=p.x+radius;++x) {
                assert(x>=0 && x<1280 && y>=0 && y<900);
                const int i=(y*1280+x)*3;
                if(visible[i]>200 && visible[i+1]>140 && visible[i+2]<130)++ink;
            }
            assert(ink>=3);
        }
        // Neutral glass between header and grid must blur the striped backdrop.
        const auto a=pixel({.04F,.175F,0}),b=pixel({.20F,.175F,0});
        auto variation=[&](const auto& rgb) {
            int low=255,high=0;
            for(int x=a.x;x<=b.x;++x){const int value=rgb[(a.y*1280+x)*3];low=std::min(low,value);high=std::max(high,value);}
            return high-low;
        };
        assert(variation(plain)>20 && variation(visible)<variation(plain)*.6F);
        // Negative case: no panel at its old location once its pose moves offscreen.
        v.latticePlacement_.openDocked({-10,0,0},glm::quat(1,0,0,0));
        v.sidebarMenus_.menus[1].open=false;v.solidWheels_.vertices.clear();
        background();v.renderMenuSurface(projection);
        assert(pixels()==plain);
        // Confirm dismisses the editor immediately, while the browser retains
        // the complete submitted request until it acknowledges the transaction.
        v.activateAuthoringTool(0);
        const auto invalidSequence=v.toolSequence_;
        v.activateSidebarAction("extrude:confirm",1);
        assert(v.toolSequence_==invalidSequence && v.extrudePanel_.active && sidebar.open);
        (void)v.extrudeLatticeDraft_.setSelected({1,4},true);
        (void)v.toolConfig_.adjustExtrudeLengthBp(32-v.toolConfig_.lengthBp());
        v.publishToolConfiguration();
        v.toolPreflightFeedback_=nadoc_vr::ToolPreflightFeedback{
            v.toolConfigSequence_,1,"ok","extrude","none","","validated"};
        assert(v.paintedExtrusionReady() && v.extrudePreviewVisible());
        sidebar.scroll(1);
        const auto settingsOffset=sidebar.offset();
        const auto submittedCells=v.extrudeLatticeDraft_.cells();
        const auto submittedConfig=v.toolConfigSequence_;
        v.thumbwheelControls_[0].begin(0);
        (void)v.thumbwheelControls_[0].drag(.12F,.01F);
        v.thumbwheelControls_[0].release();
        assert(v.thumbwheelControls_[0].moving());
        v.activateSidebarAction("extrude:confirm",1);
        assert(v.toolShell_.executionPending() && v.extrudeConfirmation_);
        assert(!v.extrudePanel_.active && !sidebar.open && !v.latticeOpen_);
        assert(!v.thumbwheelAvailable() && !v.thumbwheelControls_[0].moving() && !v.extrudePreviewVisible());
        assert(v.toolConfig_.active() && v.toolConfig_.lengthBp()==32);
        assert(v.toolConfigSequence_==submittedConfig && v.extrudeLatticeDraft_.cells()==submittedCells);
        assert(v.liveState().find("\"model_preview\":[]")!=std::string::npos);
        const auto submittedTool=v.toolSequence_;
        v.activateSidebarAction("extrude:confirm",1);
        v.activateAuthoringTool(3);
        assert(v.toolSequence_==submittedTool && v.toolShell_.mode()==nadoc_vr::ToolMode::extrude);
        v.toolExecutionFeedbackPath_=directory+"/confirm-feedback.txt";
        auto feedback=[&](const std::string& action,const std::string& status,
                          const std::string& feature="-",bool stale=false) {
            std::ofstream record(v.toolExecutionFeedbackPath_);
            record<<"NADOCVR_TOOL_EXECUTION 1 "<<v.toolExecutionFeedbackSequence_+1
                <<' '<<v.toolSequence_-(stale?1:0)<<" extrude "<<action
                <<" none - "<<status<<" test_result "<<feature<<'\n';
            record.close();v.toolExecutionFeedbackPollFrame_=2;v.pollToolExecutionFeedback();
        };
        feedback("confirm","succeeded","stale-feature",true);
        assert(v.toolShell_.executionPending() && !sidebar.open && v.toolConfig_.active());
        feedback("confirm","pending");
        assert(v.toolShell_.executionPending() && !sidebar.open && !v.latticeOpen_);
        // Acknowledged selection can advance while the submitted draft remains
        // frozen; a failed retry must still address that original draft.
        v.feedbackPath_=directory+"/selection-feedback.txt";
        v.selectSequence_=1;
        std::ofstream(v.feedbackPath_)<<"NADOCVR_FEEDBACK 3 1 1 1 cluster cluster other-target 1 other-owner\n";
        v.feedbackPollFrame_=2;v.pollSelectionFeedback();
        assert(v.selectedIdentity_=="other-target" && v.selectedSelectionKind_=="cluster");
        assert(v.toolConfig_.targetSelectionKind()=="none");
        feedback("confirm","failed");
        assert(!v.toolShell_.executionPending() && !v.extrudeConfirmation_);
        assert(v.extrudePanel_.active && sidebar.open && v.latticeOpen_);
        assert(sidebar.offset()==settingsOffset && v.extrudeLatticeDraft_.cells()==submittedCells);
        assert(v.toolConfigSequence_==submittedConfig+1 && v.extrudePreviewVisible());
        assert(v.extrudeStatus()=="EXTRUDE FAILED - ADJUST OR RETRY");
        assert(!v.paintedExtrusionReady() && !v.currentToolPreflightFeedback());
        v.activateSidebarAction("extrude:confirm",1);
        assert(v.toolSequence_==submittedTool && sidebar.open);
        auto revalidate=[&] {
            v.toolPreflightFeedback_=nadoc_vr::ToolPreflightFeedback{
                v.toolConfigSequence_,1,"ok","extrude","none","","validated"};
            assert(v.paintedExtrusionReady());
        };
        revalidate();
        v.activateSidebarAction("extrude:confirm",1);
        assert(v.toolShell_.executionPending() && v.lastToolTargetKind_=="none" &&
               v.lastToolTargetIdentity_.empty() && v.lastToolTargetOwnerTokens_.empty());
        feedback("confirm","refused");
        assert(sidebar.open && v.latticeOpen_ && v.toolConfig_.lengthBp()==32);
        assert(v.toolConfigSequence_==submittedConfig+2 && !v.paintedExtrusionReady());
        assert(v.extrudeStatus()=="EXTRUDE REFUSED - ADJUST OR RETRY");
        revalidate();
        v.activateSidebarAction("extrude:confirm",1);
        feedback("confirm","succeeded","extrude-feature");
        assert(!v.extrudePanel_.active && !sidebar.open && !v.latticeOpen_);
        assert(!v.toolConfig_.active() && v.extrudeLatticeDraft_.cells().empty() && !v.extrudePreviewVisible());
        assert(v.toolShell_.status()=="COMMITTED" && v.toolShell_.undoAvailable());
        assert(v.committedFeatureLogEntryId_=="extrude-feature");
        // Reopening starts a clean draft; Undo still addresses the saved commit.
        v.activateAuthoringTool(0);
        assert(v.toolConfig_.active() && v.toolConfig_.lengthBp()==0 && v.extrudeLatticeDraft_.cells().empty());
        assert(v.toolShell_.undoAvailable());
        v.activateSidebarAction("extrude:undo",1);
        assert(v.toolShell_.executionPending());
        assert(v.lastToolTargetKind_=="none" && v.lastToolTargetIdentity_.empty() &&
               v.lastToolTargetOwnerTokens_.empty());
        feedback("undo","succeeded","extrude-feature");
        assert(v.toolShell_.status()=="UNDONE" && !v.toolShell_.undoAvailable());
        assert(v.committedFeatureLogEntryId_.empty());
        assert(glGetError()==GL_NO_ERROR);
        std::cout<<"Existing square platform, neighbor picking, frosted panels and offscreen negative check passed\n";
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
    auto* window=glfwCreateWindow(1280,900,"Extrude validation",nullptr,nullptr);if(!window)return 77;
    glfwMakeContextCurrent(window);LiveViewerTest::run(std::filesystem::absolute(argv[1]).string());
    glfwDestroyWindow(window);glfwTerminate();
}
