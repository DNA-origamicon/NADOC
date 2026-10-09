#define NADOC_SCRYWRITE_TESTING
#define main nadoc_viewer_entry_point
#include "../src/main.cpp"
#undef main
#include <cassert>
namespace {
struct LiveViewerTest {
    static void run(const std::filesystem::path& output) {
        Viewer v(SceneData{},"");
        v.activateSidebarAction("vr:exit",0);
        assert(v.controllerPrompt_.active() && !v.exitRequested_);
        nadoc_vr::HandPose hand{true,false,{0,0,0},{1,0,0,0}};
        auto tick=[&](bool down,glm::vec2 axis,double now){v.controllerPrompt_.update(down,axis,hand,now,[](float){});};
        tick(false,{},0);tick(false,{},.2);tick(false,{},.4);
        tick(true,{-1,0},.5);tick(false,{},.6);
        assert(!v.controllerPrompt_.active() && !v.exitRequested_);
        v.activateSidebarAction("vr:exit",0);
        tick(false,{},1);tick(false,{},1.2);tick(false,{},1.4);
        tick(true,{1,0},1.5);tick(false,{},1.6);
        assert(!v.controllerPrompt_.active() && v.exitRequested_);

        SceneData unloaded;unloaded.available[size_t(Representation::full)]=true;
        v.glScene_=std::make_unique<GlScene>(std::move(unloaded));
        v.representationLoading_.enabled=true;
        v.representationLoading_.eventPath=(output/"representation").string();
        auto choose=[&](size_t option) {
            tick(false,{},2);tick(false,{},2.2);tick(false,{},2.4);
            tick(true,nadoc_vr::ControllerPrompt::direction(option,v.controllerPrompt_.request().options.size()),2.5);
            tick(false,{},2.6);
        };
        v.requestRepresentation(Representation::surfaceDetail,Coloring::strand);
        assert(v.controllerPrompt_.active() && !v.representationLoading_.pending);
        choose(0);assert(!v.representationLoading_.pending); // Cancel builds nothing.
        v.requestRepresentation(Representation::surfaceDetail,Coloring::strand);
        choose(1);assert(v.representationLoading_.pending && v.representationLoading_.target==Representation::surface);
        v.representationLoading_.cancel();
        v.requestRepresentation(Representation::surfaceDetail,Coloring::strand);
        choose(2);assert(v.representationLoading_.pending && v.representationLoading_.target==Representation::surfaceDetail);
        v.representationLoading_.fail("Surface preparation failed");
        v.pollRepresentationLoading();assert(v.controllerPrompt_.active());
        v.pollRepresentationLoading();assert(v.controllerPrompt_.queued()==1);
        const auto oldSequence=v.representationLoading_.sequence;
        choose(1);assert(v.representationLoading_.pending && v.representationLoading_.sequence>oldSequence);
        v.representationLoading_.cancel();
        v.browserPrompt_.detailAllowed=false;
        v.requestRepresentation(Representation::surfaceDetail,Coloring::strand);
        assert(!v.controllerPrompt_.active() && !v.representationLoading_.pending);
        // A prepared source is reused without asking to compute it again.
        SceneData cached;cached.available[size_t(Representation::full)]=true;cached.available[size_t(Representation::surfaceDetail)]=true;
        v.glScene_=std::make_unique<GlScene>(std::move(cached));v.browserPrompt_.detailAllowed=true;
        v.requestRepresentation(Representation::surfaceDetail,Coloring::strand);
        assert(!v.controllerPrompt_.active());
        for(size_t count=1;count<=4;++count) {
            nadoc_vr::ControllerPrompt prompt;
            nadoc_vr::ControllerPrompt::Request request{"Controller prompt", "Read the explanation here. Press the left touchpad, slide toward an option, then release to choose.",{}, {}};
            const std::array<std::string,4> labels{"Cancel","Continue","Retry","Details"};
            for(size_t i=0;i<count;++i)request.options.push_back({std::to_string(i),count==1?"OK":labels[i]});
            prompt.show(request);
            prompt.update(false,{},hand,0,[](float){});
            prompt.update(true,nadoc_vr::ControllerPrompt::direction(count-1,count),hand,.4,[](float){});
            SolidUi ui;prompt.draw(ui);assert(!ui.vertices.empty());
            const auto orientation=nadoc_vr::MenuPlacement::controllerOrientation(hand.orientation);
            const auto center=prompt.worldPoint({0,.14F,0});
            const auto vp=glm::ortho(-.35F,.35F,-.35F,.35F,.01F,10.F)*
                glm::lookAt(center+orientation*glm::vec3(0,0,2),center,orientation*glm::vec3(0,1,0));
            glViewport(0,0,700,700);glClearColor(.015F,.02F,.03F,1);
            glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT);ui.render(vp);glFinish();
            std::vector<uint8_t> rgb(700*700*3);glReadPixels(0,0,700,700,GL_RGB,GL_UNSIGNED_BYTE,rgb.data());
            size_t lit=0,cardInk=0;
            for(size_t i=0;i<rgb.size();i+=3) {
                if(rgb[i]>100 || rgb[i+1]>100 || rgb[i+2]>100)++lit;
                const size_t y=i/(700*3);
                if(y>400 && rgb[i]>150 && rgb[i+1]>150 && rgb[i+2]>150)++cardInk;
            }
            assert(lit>1000 && cardInk>200);
            const auto png=nadoc_vr::scrywrite::encodeActorEyePng(rgb,700,700);
            std::ofstream out(output/("prompt-"+std::to_string(count)+".png"),std::ios::binary);
            out.write(reinterpret_cast<const char*>(png.data()),png.size());ui.shutdown();
        }
    }
};
}
int main(int argc,char** argv) {
    if(argc!=2)return 2;
    if(!glfwInit())return 77;
    glfwWindowHint(GLFW_VISIBLE,GLFW_FALSE);glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR,3);glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR,3);
    auto* window=glfwCreateWindow(700,700,"Controller prompt test",nullptr,nullptr);
    if(!window){glfwTerminate();return 77;}
    glfwMakeContextCurrent(window);
    std::filesystem::create_directories(argv[1]);LiveViewerTest::run(argv[1]);
    glfwDestroyWindow(window);glfwTerminate();
}
