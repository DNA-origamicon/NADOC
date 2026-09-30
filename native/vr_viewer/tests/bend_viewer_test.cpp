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
        v.activateSidebarAction("tool:bend",1);
        assert(v.bendPanel_.active && !v.menuOpen_ && !v.latticeOpen_);
        assert(v.sidebarMenus_.menus[1].customTab->key=="bend");
        v.activePlanePickSequence_=17;v.planePickSlot_="b";
        v.activateSidebarAction("bend:plane1",1);
        assert(v.activePlanePickSequence_==0 && v.bendPanel_.pickSlot=="a");
        v.normalizationScale_=.6F/(100*.334F);
        (void)v.toolConfig_.setPlaneBp("a",0);(void)v.toolConfig_.setPlaneBp("b",100);
        DeformationPlaneGuide a,b;
        a.natural.center={0,0,0};a.natural.normal={0,0,1};a.natural.halfExtent=.03F;
        b=a;b.natural.center.z=.6F;
        v.planeGuides_[0]=a;v.planeGuides_[1]=b;v.bendPanel_.pickSlot.reset();
        v.bendPanel_.grabbed=0;
        v.planeGuides_[1]->natural.normal=glm::normalize(glm::vec3(.2F,0,1));
        v.prepareBendArc();
        assert(v.bendPanel_.arc.fixedEnd==1);
        assert(glm::distance(v.bendPanel_.arc.tangent,v.planeGuides_[1]->natural.normal)<1e-6F);
        v.planeGuides_[1]=b;v.bendPanel_.grabbed=1;
        v.prepareBendArc();
        v.hands_[1].valid=true;v.hands_[1].position=v.bendHandle(1);
        v.triggerClicked_[1]=true;v.triggerPressed_[1]=true;
        std::array<bool,2> blocked{};
        v.processBendHandles(blocked,false);
        assert(v.bendPanel_.hand==1 && blocked[1]);
        v.triggerClicked_[1]=false;
        const auto fixed=v.bendPanel_.arc.a;
        // Replay all existing noise presets when supplied by the profile harness.
        std::ifstream samples(directory+"/motion.txt");
        float x,y,z;
        if(samples)while(samples>>x>>y>>z) {
            v.hands_[1].position={x,y,z};blocked.fill(false);v.processBendHandles(blocked,false);
            assert(v.bendPanel_.arc.a==fixed);
            assert(glm::distance(v.bendPanel_.arc.endTangent(0),a.natural.normal)<1e-6F);
            assert(glm::distance(v.bendPanel_.arc.a,v.bendPanel_.arc.b)<=v.bendPanel_.arc.length+1e-5F);
        }
        else {v.hands_[1].position={.25F,0,.4F};blocked.fill(false);v.processBendHandles(blocked,false);}
        assert(v.bendPanel_.posed && v.toolConfig_.bendAngleDegrees()>0);
        v.hands_[0].valid=true;v.hands_[0].position=v.bendHandle(0);v.triggerClicked_[0]=true;v.triggerPressed_[0]=true;
        blocked.fill(false);v.processBendHandles(blocked,false);assert(v.bendPanel_.hand==1);
        v.triggerPressed_[1]=false;v.processBendHandles(blocked,false);assert(!v.bendPanel_.hand);
        std::ifstream event(directory+"/events.json");std::string json((std::istreambuf_iterator<char>(event)),{});
        assert(json.find("bend_endpoints")!=std::string::npos && json.find("bend_midpoint")!=std::string::npos);
        // Switching to the unmoved end resets both ends to the original planes.
        blocked.fill(false);v.processBendHandles(blocked,false);assert(v.bendPanel_.hand==0);
        assert(glm::distance(v.bendPanel_.arc.a,a.natural.center)<1e-6F);
        assert(glm::distance(v.bendPanel_.arc.b,b.natural.center)<1e-6F);
        assert(v.toolConfig_.bendAngleDegrees()==0);
        const auto fixedB=v.bendPanel_.arc.b;
        v.triggerClicked_[0]=false;
        v.hands_[0].position.x-=.08F;
        v.hands_[0].position.y-=.08F;
        v.hands_[0].position.z+=.10F;blocked.fill(false);v.processBendHandles(blocked,false);
        assert(v.bendPanel_.arc.b==fixedB);
        assert(glm::distance(v.bendPanel_.arc.endTangent(1),b.natural.normal)<1e-6F);
        assert(std::abs(v.toolConfig_.bendDirectionDegrees()-45)<.01);
        const auto rows=v.sidebarMenus_.menus[1].customTab->rows;
        assert(std::any_of(rows.begin(),rows.end(),[](const auto& row){return row.label=="Direction: 45 deg";}));
        assert(std::any_of(rows.begin(),rows.end(),[&](const auto& row){return row.label=="Angle: "+std::to_string(int(std::round(v.toolConfig_.bendAngleDegrees())))+" deg";}));
        // The free hand can adjust direction while the first still holds the end.
        v.triggerPressed_[1]=true;
        const auto beforeDirection=v.bendPanel_.arc.b-v.bendPanel_.arc.a;
        v.activateSidebarAction("bend:direction",1);
        assert(v.bendPanel_.wheelHand==1);
        auto wheelLocal=v.sidebarMenus_.menus[1].placement.localPoint(v.hands_[1].position);
        wheelLocal.y+=.045F;
        v.hands_[1].position=v.sidebarMenus_.menus[1].placement.worldPoint(wheelLocal);
        v.processBendWheel(blocked);
        assert(std::abs(v.toolConfig_.bendDirectionDegrees()-46)<.01);
        assert(v.bendPanel_.arc.b==fixedB);
        assert(glm::distance(v.bendPanel_.arc.endTangent(1),b.natural.normal)<1e-6F);
        const auto expected=glm::angleAxis(glm::radians(1.F),v.bendPanel_.arc.tangent)*beforeDirection;
        assert(glm::distance(v.bendPanel_.arc.b-v.bendPanel_.arc.a,expected)<1e-6F);
        v.processBendHandles(blocked,false);
        assert(std::abs(v.toolConfig_.bendDirectionDegrees()-46)<.01);
        v.triggerPressed_[1]=false;v.processBendWheel(blocked);
        v.processBendHandles(blocked,false);
        assert(glm::distance(v.bendPanel_.arc.b-v.bendPanel_.arc.a,expected)<1e-6F);
        v.triggerPressed_[0]=false;v.processBendHandles(blocked,false);
        // Regrabbing the moved end retains the bend instead of resetting it.
        const auto retained=v.bendPanel_.arc.a;
        v.hands_[0].position=v.bendHandle(0);v.triggerPressed_[0]=true;v.triggerClicked_[0]=true;
        blocked.fill(false);v.processBendHandles(blocked,false);
        assert(v.bendPanel_.hand==0);
        assert(v.bendPanel_.arc.a==retained && v.bendPanel_.arc.b==fixedB);
        v.triggerPressed_[0]=false;v.triggerClicked_[0]=false;v.processBendHandles(blocked,false);
        v.refreshExtrudePanel();
        v.sidebarMenus_.menus[1].focus.id="bend:plane1";
        v.sidebarMenus_.menus[1].navigate({1,0});
        assert(v.sidebarMenus_.menus[1].focus.id=="bend:plane2");
        const auto oldAngle=v.toolConfig_.bendAngleDegrees();
        v.triggerPressed_[1]=true;
        v.activateSidebarAction("bend:angle",1);
        const auto& placement=v.sidebarMenus_.menus[1].placement;
        auto local=placement.localPoint(v.hands_[1].position);local.y+=.045F;
        v.hands_[1].position=placement.worldPoint(local);blocked.fill(false);v.processBendWheel(blocked);
        assert(blocked[1] && v.toolConfig_.bendAngleDegrees()==std::round(oldAngle)+1);
        v.triggerPressed_[1]=false;v.processBendWheel(blocked);
        v.toggleMenu(1);assert(v.sidebarMenus_.menus[1].open);
        const auto stepDirection=v.toolConfig_.bendDirectionDegrees();
        v.activateSidebarAction("bend:direction-more",1);
        assert(std::abs(v.toolConfig_.bendDirectionDegrees()-std::fmod(stepDirection+5,360.0))<1e-5);
        v.activateSidebarAction("bend:direction-less",1);
        assert(std::abs(v.toolConfig_.bendDirectionDegrees()-stepDirection)<1e-5);
        const auto radiusBefore=33.4/glm::radians(v.toolConfig_.bendAngleDegrees());
        v.activateSidebarAction("bend:radius-more",1);
        assert(std::abs(33.4/glm::radians(v.toolConfig_.bendAngleDegrees())-radiusBefore-10)<1e-5);
        assert(v.bendPanel_.arc.b==fixedB);
        assert(glm::distance(v.bendPanel_.arc.endTangent(1),b.natural.normal)<1e-6F);
        v.activateSidebarAction("bend:radius-less",1);
        assert(std::abs(33.4/glm::radians(v.toolConfig_.bendAngleDegrees())-radiusBefore)<1e-5);
        for(size_t slot=0;slot<2;++slot) {
            const auto plane=v.deformationPlanePose(slot);
            assert(glm::distance(plane.center,slot==0?v.bendPanel_.arc.a:v.bendPanel_.arc.b)<1e-6F);
            assert(glm::distance(plane.normal,v.bendPanel_.arc.endTangent(float(slot)))<1e-6F);
        }
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
        std::ofstream ppm(directory+"/bend-preview.ppm",std::ios::binary);ppm<<"P6\n128 128\n255\n";
        for(int y=127;y>=0;--y)ppm.write(reinterpret_cast<const char*>(visible.data()+y*128*3),128*3);
        assert(v.bendReady());
        v.activateSidebarAction("bend:confirm",1);assert(v.toolShell_.executionPending());
        std::cout<<"Bend trigger, fixed ends, wheel, touchpad and rendered preview passed\n";
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
    auto* window=glfwCreateWindow(128,128,"Bend validation",nullptr,nullptr);if(!window)return 77;
    glfwMakeContextCurrent(window);
    LiveViewerTest::run(argv[1]);
    glfwDestroyWindow(window);glfwTerminate();
}
