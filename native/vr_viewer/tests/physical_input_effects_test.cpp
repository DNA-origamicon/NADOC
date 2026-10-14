// Spy only on this test translation unit's OpenXR haptic dispatch. This never
// launches OpenXR, sends controller vibration, or sends desktop input events.
#define xrApplyHapticFeedback nadocTestApplyHapticFeedback
#define NADOC_SCRYWRITE_TESTING
#define main nadoc_viewer_entry_point
#include "../src/main.cpp"
#undef main
#undef xrApplyHapticFeedback
#include <cassert>

namespace { unsigned hapticCalls=0; float lastAmplitude=0;XrResult hapticResult=XR_SUCCESS; }
extern "C" XRAPI_ATTR XrResult XRAPI_CALL nadocTestApplyHapticFeedback(
    XrSession, const XrHapticActionInfo*, const XrHapticBaseHeader* feedback) {
    ++hapticCalls;
    assert(feedback->type==XR_TYPE_HAPTIC_VIBRATION);
    lastAmplitude=reinterpret_cast<const XrHapticVibration*>(feedback)->amplitude;
    return hapticResult;
}
namespace {
struct LiveViewerTest {
    static void run(const std::string& directory) {
        Viewer viewer(SceneData{});
        nadoc_vr::CaptureUiFrame diagnostic;
        viewer.captureUiDiagnostics_.begin(&diagnostic);
        assert(viewer.physicalEffectsEnabled() && !viewer.liveControlsEnabled());
        viewer.pulse(0,.2F);assert(hapticCalls==1 && lastAmplitude==.2F);
        assert(diagnostic.requested[0]==1 && diagnostic.dispatched[0]==1 && diagnostic.events[0].result==XR_SUCCESS);
        hapticResult=XR_SESSION_NOT_FOCUSED;
        viewer.pulse(0,.25F);
        assert(diagnostic.events[1].result==XR_SESSION_NOT_FOCUSED && diagnostic.events[1].dispatched);
        hapticResult=XR_ERROR_RUNTIME_FAILURE;
        bool failed=false;try{viewer.pulse(0,.25F);}catch(const std::runtime_error&){failed=true;}
        assert(failed && diagnostic.failed[0]==1 && diagnostic.events[2].result==XR_ERROR_RUNTIME_FAILURE);
        assert(diagnostic.events[2].endNs>=diagnostic.events[2].beginNs);
        hapticResult=XR_SUCCESS;
        viewer.liveSocket_.open(directory+"/test.sock");
        viewer.liveSession_="123-456";
        for(const auto* mode:{"inspect","control","transactions","inspect"}) {
            viewer.liveMode_=mode;
            const bool physical=std::string(mode)=="inspect";
            assert(viewer.physicalEffectsEnabled()==physical);
            assert(viewer.liveControlsEnabled()!=physical);
            const unsigned before=hapticCalls;
            viewer.pulse(1,.6F);
            assert(hapticCalls==before+unsigned(physical));
            const auto& e=diagnostic.events[diagnostic.eventCount-1];
            assert(e.dispatched==physical && e.callsiteLine>0);
            if(physical) {
                const auto position=viewer.hands_[1].position;
                const auto sequence=viewer.liveCommandSequence_;
                const auto reply=viewer.liveCommand("123-456 "+std::to_string(sequence+1)+" pose 1 0 1 -0.3 0 0 0 1");
                assert(reply.find("read_only")!=std::string::npos);
                assert(viewer.liveCommandSequence_==sequence && viewer.hands_[1].position==position);
            }
        }
        viewer.captureUiDiagnostics_.end();
    }
};
}
int main(int argc,char** argv) {
    assert(argc==2 || argc==3);
    if(argc==3) {
        if(!glfwInit())return 77;
        glfwWindowHint(GLFW_VISIBLE,GLFW_FALSE);glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR,3);glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR,3);
        GLFWwindow* window=glfwCreateWindow(128,128,"capture-ui-test",nullptr,nullptr);
        if(!window){glfwTerminate();return 77;}glfwMakeContextCurrent(window);
        SidebarRuntime sidebar;sidebar.initialize();sidebar.menus[0].open=true;
        nadoc_vr::CaptureUiFrame f;nadoc_vr::CaptureUiDiagnostics diag;
        diag.begin(&f);sidebar.draw(&diag);assert(f.sidebars[0].updates==1 && f.sidebars[0].drawCalls==1);
        diag.end();diag.begin(&f);sidebar.draw(&diag);assert(f.sidebars[0].updates==0 && f.sidebars[0].hits==1);
        bool selected=false;
        for(const auto& c:sidebar.menus[0].controls())if(c.enabled && !c.active){sidebar.menus[0].hovered=c.id;selected=true;break;}
        assert(selected);diag.end();diag.begin(&f);sidebar.draw(&diag);
        assert(f.sidebars[0].updates==1 && f.sidebars[0].textureHostNs>0 && f.sidebars[0].drawHostNs>=f.sidebars[0].textureHostNs);
        assert(glGetError()==GL_NO_ERROR);
        diag.end();sidebar.shutdown();glfwDestroyWindow(window);glfwTerminate();
        std::cout<<"Actual GL sidebar texture rebuild, cache hit and hover invalidation diagnostics passed\n";return 0;
    }
    std::filesystem::create_directories(argv[1]);
    std::filesystem::permissions(argv[1],std::filesystem::perms::owner_all);
    LiveViewerTest::run(argv[1]);
    std::cout<<"Physical/inspect haptic dispatch, synthetic-effect suppression and inspect input rejection passed\n";
}
