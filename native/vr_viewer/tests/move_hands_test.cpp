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
        v.sessionState_=XR_SESSION_STATE_FOCUSED;
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
