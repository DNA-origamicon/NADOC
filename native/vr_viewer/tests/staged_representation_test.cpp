#define main nadoc_viewer_entry_point
#include "../src/main.cpp"
#undef main
#include <cassert>
int main(){
    RepresentationLoading loading;loading.pending=true;
    for(int i=0;i<3;++i){loading.recordFrameGap(22.3,11.111);loading.recordFrameGap(11.1,11.111);}
    assert(loading.lightweight); // Clustered misses need not be consecutive.
    loading.pending=false;loading.recordFrameGap(11.1,11.111);assert(!loading.lightweight);
    loading.pending=true;
    for(int i=0;i<3;++i)loading.recordFrameGap(22.3,22.222);
    assert(loading.lightweight); // Reprojection cannot relax the target budget.
    if(!glfwInit())return 77;
    glfwWindowHint(GLFW_VISIBLE,GLFW_FALSE);glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR,4);glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR,3);
    auto* window=glfwCreateWindow(64,64,"staged representation",nullptr,nullptr);
    if(!window)return 77;glfwMakeContextCurrent(window);glEnable(GL_PROGRAM_POINT_SIZE);
    {
        // Exercise the guard's actual drawing path with every primitive family,
        // including a cylinder-only Stick scene (no atom spheres to fall back on).
        for(int kind=0;kind<4;++kind){
            SceneData data;data.available.fill(true);
            auto& rep=data.representations[representationSourceIndex(Representation::full)];
            ColorSet colors;colors.values.fill({1,.5F,.25F});
            if(kind==0)rep.points.push_back({"atom",{0,0,-2},colors,.1F});
            if(kind==1)rep.cylinders.push_back({"bond",{-.2F,0,-2},{.2F,0,-2},.1F,colors});
            if(kind==2)rep.halfCylinders.push_back({"half",{-.2F,0,-2},{.2F,0,-2},.1F,colors});
            if(kind==3){StyledBox box;box.identity="box";box.center={0,0,-2};box.colors=colors;rep.boxes.push_back(box);}
            GlScene model(std::move(data),true,{}, {},false);
            const auto before=model.representation();
            auto pixels=[&](float eye,float x){
                glViewport(0,0,64,64);glClearColor(0,0,0,0);glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT);
                const auto vp=glm::perspective(glm::radians(90.F),1.F,.05F,100.F)*glm::translate(glm::mat4(1),glm::vec3(eye,0,0));
                model.renderVolumes(vp,glm::translate(glm::mat4(1),glm::vec3(x,0,0)),{},false,{},true);
                std::array<unsigned char,64*64*4> rgb{};glReadPixels(0,0,64,64,GL_RGBA,GL_UNSIGNED_BYTE,rgb.data());
                size_t lit=0;for(size_t i=0;i<rgb.size();i+=4)lit+=rgb[i]>100;
                assert(glGetError()==GL_NO_ERROR);return lit;
            };
            for(float eye:{-.03F,.03F}){
                assert(pixels(eye,0)>0);assert(pixels(eye,.5F)>0);
                assert(pixels(eye,100)==0); // Offscreen negative control.
            }
            assert(model.representation()==before);
        }
        RepresentationData source;
        for(int i=0;i<20000;++i){StyledPoint p;p.identity="atom:"+std::to_string(i);p.position={float(i),2,3};p.size=.25F;p.vdwSize=.75F;p.colors.values[3]={.1F,.2F,.3F};source.points.push_back(p);}
        auto index=std::make_shared<SourceIndex>();index->rebuild(source);
        auto prepared=prepareStaticRepresentation(source,Representation::vdw,index);
        assert(prepared->points.front().size==.75F);
        StagedRepresentation stage;stage.start(prepared,Coloring::cpk);
        auto ids=[](const std::string& id){return uint32_t(std::stoi(id.substr(5))+1);};
        assert(!stage.poll(ids));assert(stage.pending());assert(stage.progress()<1);
        stage.cancel();assert(!stage.pending());
        stage.start(prepared,Coloring::cpk);
        std::shared_ptr<ResidentRepresentation> ready;
        const auto end=std::chrono::steady_clock::now()+std::chrono::seconds(5);
        while(!ready && std::chrono::steady_clock::now()<end){
            const double before=stage.progress();ready=stage.poll(ids);
            if(!ready)assert((stage.progress()-before)*prepared->bytes()<=256*1024+1);
        }
        assert(ready && ready->counts[0]==20000 && !stage.pending());
        std::array<Vertex,2> actual{};glBindBuffer(GL_ARRAY_BUFFER,ready->buffers[0]);
        glGetBufferSubData(GL_ARRAY_BUFFER,0,sizeof(actual),actual.data());
        assert(actual[0].position==glm::vec3(0,2,3) && actual[1].objectId==2);
        assert(actual[0].color==glm::vec3(.1F,.2F,.3F) && actual[0].size==.75F);
        assert(glGetError()==GL_NO_ERROR);
        SceneData scene;scene.available.fill(true);
        scene.representations[representationSourceIndex(Representation::full)]=std::move(source);
        auto& natural=scene.representations[representationSourceIndex(Representation::full)];
        auto fullIndex=std::make_shared<SourceIndex>();fullIndex->rebuild(natural);
        scene.prepared[size_t(Representation::full)]=prepareStaticRepresentation(natural,Representation::full,fullIndex);
        scene.prepared[size_t(Representation::beads)]=prepareStaticRepresentation(natural,Representation::beads,fullIndex);
        SceneData copy=scene;assert(!copy.prepared[size_t(Representation::full)]);
        assert(copy.representations[representationSourceIndex(Representation::full)].points.size()==20000);
        GlScene display(std::move(scene),false,{}, {},false);display.enablePreparedStyles();
        display.setStyle(Representation::beads,Coloring::cpk);
        assert(display.stylePending() && display.representation()==Representation::full);
        while(display.stylePending() && std::chrono::steady_clock::now()<end)display.pollPreparedStyle();
        assert(display.representation()==Representation::beads && !display.stylePending());
        display.setStyle(Representation::full,Coloring::cpk);assert(display.stylePending());
        display.cancelPreparedStyle();assert(display.representation()==Representation::beads);
        display.setStyle(Representation::beads,Coloring::cpk);assert(!display.stylePending());
        assert(glGetError()==GL_NO_ERROR);
        SceneData initial;initial.available[size_t(Representation::full)]=true;
        display.installInitialScene(std::move(initial));
        assert(!display.supportsRepresentation(Representation::surface));
        SceneData cached;cached.available[size_t(Representation::full)]=true;cached.available[size_t(Representation::surface)]=true;
        cached.representations[size_t(Representation::surface)].points.resize(20000);
        cached.cpuBytes[size_t(Representation::surface)]=representationCpuBytes(cached.representations[size_t(Representation::surface)]);
        GlScene limited(std::move(cached),false,{}, {},false);
        SceneRetirement retired;limited.trimPreparedCache(retired,0);
        assert(limited.supportsRepresentation(Representation::full));
        assert(!limited.supportsRepresentation(Representation::surface));
    }
    glfwDestroyWindow(window);glfwTerminate();
    std::cout<<"Chunk limits, cancellation, GPU bytes, atomic activation and resident reuse passed\n";
}
