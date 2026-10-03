#define NADOC_SCRYWRITE_TESTING
#define main nadoc_viewer_entry_point
#include "../src/main.cpp"
#undef main
#include <cassert>

using Clock=std::chrono::steady_clock;
double elapsed(Clock::time_point start){return std::chrono::duration<double,std::milli>(Clock::now()-start).count();}
SceneData fixture(float x) {
    SceneData data;data.available.fill(true);
    ColorSet colors;colors.values.fill({.35F,.65F,.9F});
    for(size_t i=0;i<kRepresentationCount;++i){
        auto& s=data.representations[i];
        s.points.push_back({"point",{x,.1F,-1.3F},colors,.05F});
        s.points.push_back({x==0?"removed":"added",{.3F,.1F,-1.3F},colors,.04F});
        s.cylinders.push_back({"bond",{x,.1F,-1.3F},{.3F,.1F,-1.3F},.025F,colors});
        s.halfCylinders.push_back({"half",{-.2F,-.2F,-1.3F},{.2F,-.2F,-1.3F},.04F,colors});
        s.boxes.push_back({"box",{0,-.05F,-1.3F},{.1F,0,0},{0,.04F,0},{0,0,.04F},colors});
        s.ownerHandles.push_back({"cluster",{0,0,-1.3F}});
        s.ownerAliases={{"point",{"cluster"}},{"bond",{"cluster"}}};
        s.toolScopeOwnership={{"point",{{"cluster",1,1}}},{"bond",{{"cluster",1,0}}}};
        auto index=std::make_shared<SourceIndex>();index->rebuild(s);
        data.prepared[i]=prepareStaticRepresentation(s,static_cast<Representation>(i),index);
    }
    return data;
}
struct Frame {std::vector<unsigned char> rgb;std::vector<float> depth;};
Frame capture(GlScene& scene,int size=128) {
    scene.renderShadowMap(glm::mat4(1),{{-.577F,.577F,.577F},{0,1,0}});
    glBindFramebuffer(GL_FRAMEBUFFER,0);glViewport(0,0,size,size);glDrawBuffer(GL_BACK);
    glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT);
    scene.render(glm::perspective(glm::radians(70.F),1.F,.02F,100.F),glm::mat4(1),{},false);
    Frame f;f.rgb.resize(size*size*4);f.depth.resize(size*size);
    glReadPixels(0,0,size,size,GL_RGBA,GL_UNSIGNED_BYTE,f.rgb.data());
    glReadPixels(0,0,size,size,GL_DEPTH_COMPONENT,GL_FLOAT,f.depth.data());
    assert(glGetError()==GL_NO_ERROR);return f;
}
void parity() {
    SceneRetirement retired;
    GlScene scene(fixture(0),true,{}, {},false);
    scene.setSelectionHighlights({}, {},{"cluster"},{});
    for(float x:{-.2F,0.F,.15F}) {
        const auto before=capture(scene);const auto ids=scene.objectIdentities();
        GlScene reference(fixture(x),true,ids,{},false);
        reference.setSelectionHighlights({}, {},{"cluster"},{});
        nadoc_vr::VisualizationSnapshot snapshot;
        scene.beginSceneRefresh(fixture(x));
        assert(scene.canStageSceneRefresh(snapshot));
        auto colored=snapshot;colored.points.resize(1);
        assert(!scene.canStageSceneRefresh(colored));
        assert(!scene.advanceSceneRefresh(snapshot,retired,0));
        assert(capture(scene).rgb==before.rgb); // Old scene stays fully visible.
        // A style change during upload must restart the pending representation.
        snapshot.representation="beads";snapshot.coloring="strand";
        assert(!scene.advanceSceneRefresh(snapshot,retired,0));
        snapshot.representation="full";
        const auto deadline=Clock::now()+std::chrono::seconds(5);
        bool applied=false;
        while(!applied && Clock::now()<deadline){
            applied=scene.advanceSceneRefresh(snapshot,retired);
            if(!applied)assert(capture(scene).rgb==before.rgb);
        }
        assert(applied);
        for(size_t i=0;i<ids.size();++i)assert(scene.objectIdentities()[i]==ids[i]);
        auto actual=capture(scene),expected=capture(reference);
        assert(actual.rgb==expected.rgb && actual.depth==expected.depth);
        assert(actual.rgb!=before.rgb);
        size_t visible=0;for(size_t i=0;i<actual.rgb.size();i+=4)visible+=actual.rgb[i]>0;
        assert(visible>30);
        for(float rx:{-.2F,0.F,.3F}){
            nadoc_vr::Ray ray{{rx,.1F,0},{0,0,-1}};
            const auto a=scene.pick(ray,glm::mat4(1)),b=reference.pick(ray,glm::mat4(1));
            assert(bool(a)==bool(b));if(a)assert(a->identity==b->identity && std::abs(a->distance-b->distance)<1e-6F);
        }
        const auto transform=glm::translate(glm::mat4(1),glm::vec3(.03F,0,0));
        scene.setToolPreview({"cluster"},transform);reference.setToolPreview({"cluster"},transform);
        assert(capture(scene).rgb==capture(reference).rgb);
        scene.setToolPreview({},glm::mat4(1));
    }
    scene.beginSceneRefresh(fixture(.2F));
    auto canceled=scene.takeSceneRefresh();retired.retire(std::move(canceled));
    assert(!scene.canStageSceneRefresh({}));
    std::cout<<"ACTIVATION_PARITY old scene, atomic swap, pixels/depth/picking, stable IDs, style restart, repeated edits/Undo, preview and cancellation passed\n";
}
void benchmark(const char* path) {
    for(bool staged:{false,true}) {
        auto initial=loadScene(path);const auto rep=initial.initialRepresentation;
        const auto& source=initial.representations[representationSourceIndex(rep)];
        const std::vector<std::string> owners=source.ownerHandles.empty()?std::vector<std::string>{}:std::vector<std::string>{source.ownerHandles.front().token};
        auto scene=std::make_unique<GlScene>(std::move(initial),true,std::deque<std::string>{},std::function<void(size_t)>{},false);
        scene->setSelectionHighlights({}, {},owners,{});
        auto replacement=loadScene(path);SceneRetirement retired;
        capture(*scene);glFinish();
        nadoc_vr::VisualizationSnapshot snapshot;
        std::vector<double> slices;
        const auto start=Clock::now();
        if(staged)scene->beginSceneRefresh(std::move(replacement));
        bool done=false;
        do {
            const auto slice=Clock::now();
            if(staged)done=scene->advanceSceneRefresh(snapshot,retired);
            else {
                auto candidate=std::make_unique<GlScene>(std::move(replacement),true,scene->objectIdentities(),std::function<void(size_t)>{},false,false);
                candidate->setSelectionHighlights({}, {},owners,{},false);
                candidate->setVisualization(snapshot);scene.swap(candidate);candidate->retireSource(retired);
                done=true;
            }
            slices.push_back(elapsed(slice));capture(*scene);
            assert(elapsed(start)<30000);
        } while(!done);
        const auto total=elapsed(start);std::sort(slices.begin(),slices.end());
        std::cout<<"ACTIVATION_RESULT staged="<<staged<<" slices="<<slices.size()<<" update_p95_ms="<<slices[size_t(.95*slices.size())]
            <<" update_max_ms="<<slices.back()<<" elapsed_ms="<<total<<std::endl;
    }
}
int main(int argc,char** argv) {
    if(!glfwInit())return 77;
    glfwWindowHint(GLFW_VISIBLE,GLFW_FALSE);glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR,4);glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR,3);
    auto* window=glfwCreateWindow(128,128,"scene activation",nullptr,nullptr);if(!window)return 77;
    glfwMakeContextCurrent(window);glfwSwapInterval(0);glEnable(GL_DEPTH_TEST);
    if(argc==2)benchmark(argv[1]);else parity();
    glfwDestroyWindow(window);glfwTerminate();
}
