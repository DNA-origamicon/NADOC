// Exercise the production trigger, wheel, panel, transport and GL guide paths.
#define NADOC_SCRYWRITE_TESTING
#define main nadoc_viewer_entry_point
#include "../src/main.cpp"
#undef main
#include <cassert>
namespace {
struct LiveViewerTest {
    static void run(const std::string& directory) {
        Viewer v(SceneData{},directory+"/events.json");
        v.liveSocket_.open(directory+"/test.sock"); // Suppress physical haptics.
        SceneData data;data.available.fill(true);
        v.glScene_=std::make_unique<GlScene>(std::move(data));
        v.selectedIdentity_="test";v.selectedSelectionKind_="cluster";v.selectedOwnerTokens_={"owner"};
        v.activateSidebarAction("tool:twist",1);
        assert(v.bendPanel_.active && !v.latticeOpen_);
        assert(v.sidebarMenus_.menus[1].customTab->key=="twist");
        v.activePlanePickSequence_=17;v.planePickSlot_="b";
        v.activateSidebarAction("twist:plane1",1);
        assert(v.activePlanePickSequence_==0 && v.bendPanel_.pickSlot=="a");
        v.normalizationScale_=.6F/(100*.334F);
        (void)v.toolConfig_.setPlaneBp("a",0);(void)v.toolConfig_.setPlaneBp("b",100);
        DeformationPlaneGuide a,b;
        a.natural.center={0,0,0};a.natural.normal={0,0,1};a.natural.halfExtent=.03F;
        b=a;b.natural.center.z=.6F;
        v.planeGuides_[0]=a;v.planeGuides_[1]=b;v.bendPanel_.pickSlot.reset();
        v.prepareBendArc();
        const auto fixedA=v.bendPanel_.arc.a,fixedB=v.bendPanel_.arc.b;
        v.hands_[1].valid=true;v.hands_[1].position=v.twistHandle(1);
        v.triggerClicked_[1]=true;v.triggerPressed_[1]=true;
        std::array<bool,2> blocked{};
        v.processBendHandles(blocked,false);assert(v.bendPanel_.hand==1 && blocked[1]);
        assert(!v.bendReady());
        v.triggerClicked_[1]=false;
        const auto radial=v.hands_[1].position-fixedB;
        const auto before=v.toolConfig_.twistTotalDegrees();
        for(int i=1;i<=20;++i) {
            v.hands_[1].position=fixedB+glm::angleAxis(glm::radians(i*5.F),glm::vec3(0,0,1))*radial;
            blocked.fill(false);v.processBendHandles(blocked,false);
        }
        assert(std::abs(v.toolConfig_.twistTotalDegrees()-before-100)<.001);
        assert(v.bendPanel_.arc.a==fixedA && v.bendPanel_.arc.b==fixedB);
        v.hands_[0].valid=true;v.hands_[0].position=v.twistHandle(1);v.triggerClicked_[0]=true;v.triggerPressed_[0]=true;
        blocked.fill(false);v.processBendHandles(blocked,false);assert(v.bendPanel_.hand==1);
        v.triggerPressed_[1]=false;v.processBendHandles(blocked,false);assert(!v.bendPanel_.hand);
        v.triggerPressed_[0]=false;v.triggerClicked_[0]=false;
        v.activateSidebarAction("twist:units",1);
        assert(std::abs(v.toolConfig_.twistTotalDegrees()-before-100)<.001);
        v.activateSidebarAction("twist:reverse",1);
        assert(v.toolConfig_.twistTotalDegrees()<0);
        v.triggerPressed_[1]=true;v.activateSidebarAction("twist:amount",1);
        const auto amount=v.toolConfig_.twistAmount();
        auto local=v.sidebarMenus_.menus[1].placement.localPoint(v.hands_[1].position);local.y+=.045F;
        v.hands_[1].position=v.sidebarMenus_.menus[1].placement.worldPoint(local);
        v.processBendWheel(blocked);assert(std::abs(v.toolConfig_.twistAmount()-(std::round(amount*10)+1)/10)<1e-6);
        v.triggerPressed_[1]=false;v.processBendWheel(blocked);
        v.toggleMenu(1);assert(v.sidebarMenus_.menus[1].open);
        v.activateSidebarAction("twist:zero",1);assert(v.toolConfig_.twistAmount()==0);
        v.activateSidebarAction("twist:more",1);assert(v.toolConfig_.twistAmount()==.5);
        v.activateSidebarAction("twist:less",1);assert(v.toolConfig_.twistAmount()==0);
        v.activateSidebarAction("twist:more",1);
        // Frame the curve from the side so the actual preview has measurable pixels.
        v.sidebarMenus_.menus[1].open=false;
        std::vector<Vertex> guides;
        v.drawBend([&](auto a,auto b,auto c){guides.push_back({a,c,1});guides.push_back({b,c,1});});
        glm::vec3 minimum(1e6F),maximum(-1e6F);
        for(const auto& g:guides) {minimum=glm::min(minimum,g.position);maximum=glm::max(maximum,g.position);}
        const auto center=(minimum+maximum)*.5F;
        const float extent=std::max(maximum.x-minimum.x,maximum.z-minimum.z)*.5F+.06F;
        auto matrix=glm::ortho(-extent,extent,-extent,extent,.01F,10.F)*glm::lookAt(center+glm::vec3(0,-2,0),center,glm::vec3(0,0,1));
        auto render=[&](const glm::mat4& vp) {
            glViewport(0,0,128,128);glClearColor(0,0,0,1);glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT);
            v.glScene_->renderGuides(vp,guides);
            std::vector<unsigned char> pixels(128*128*3);glReadPixels(0,0,128,128,GL_RGB,GL_UNSIGNED_BYTE,pixels.data());return pixels;
        };
        const auto visible=render(matrix);
        auto count=[](const auto& pixels){return std::count_if(pixels.begin(),pixels.end(),[](auto c){return c>80;});};
        assert(count(visible)>100);
        const auto hidden=render(matrix*glm::translate(glm::mat4(1),glm::vec3(10,0,0)));
        assert(count(hidden)==0);
        std::ofstream ppm(directory+"/twist-preview.ppm",std::ios::binary);ppm<<"P6\n128 128\n255\n";
        for(int y=127;y>=0;--y)ppm.write(reinterpret_cast<const char*>(visible.data()+y*128*3),128*3);
        assert(v.bendReady());
        v.activateSidebarAction("twist:confirm",1);assert(v.toolShell_.executionPending());
        std::cout<<"Twist rotation, fixed planes, units, signed wheel and rendered preview passed\n";
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
    auto* window=glfwCreateWindow(128,128,"Twist validation",nullptr,nullptr);if(!window)return 77;
    glfwMakeContextCurrent(window);
    LiveViewerTest::run(argv[1]);
    glfwDestroyWindow(window);glfwTerminate();
}
