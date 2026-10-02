// Diagnostic only: runs the production GlScene preview/update/render paths.
#define NADOC_SCRYWRITE_TESTING
#define main nadoc_viewer_entry_point
#include "../src/main.cpp"
#undef main
#include <cassert>
using Clock = std::chrono::steady_clock;
double ms(Clock::time_point a, Clock::time_point b) {return std::chrono::duration<double,std::milli>(b-a).count();}
void stats(const char* key, std::vector<double> x) {std::sort(x.begin(),x.end()); std::cout<<" "<<key<<"_p50_ms="<<x[x.size()/2]<<" "<<key<<"_p95_ms="<<x[size_t(x.size()*.95)];}
int benchmark(int argc,char** argv) {
 if(argc!=5 || !glfwInit())return 2;
 glfwWindowHint(GLFW_VISIBLE,GLFW_FALSE);glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR,4);glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR,3);
 auto* window=glfwCreateWindow(1852,2056,"preview diagnostic",nullptr,nullptr);if(!window)return 3;
 glfwMakeContextCurrent(window);glfwSwapInterval(0);glEnable(GL_DEPTH_TEST);
 std::cout<<"GPU "<<glGetString(GL_RENDERER)<<std::endl;
 {
 auto data=loadScene(argv[1]);auto rep=representationFromName(argv[2]);data.initialRepresentation=rep;
 const auto& src=data.representations[representationSourceIndex(rep)];
 std::string owner;glm::vec3 pivot;
 if(std::string(argv[3])=="cluster") {assert(!src.ownerHandles.empty());owner=src.ownerHandles.front().token;pivot=src.ownerHandles.front().center;}
 else {for(const auto& h:src.toolHandles)if(h.kind=="base") {owner=h.token;pivot=h.center;break;}}
 assert(!owner.empty());
 std::cout<<"FIXTURE rep="<<argv[2]<<" owner="<<argv[3]<<" points="<<src.points.size()<<" cylinders="<<src.cylinders.size()<<" boxes="<<src.boxes.size()<<" ownership="<<src.toolScopeOwnership.size()<<" token="<<owner<<std::endl;
 const bool volumes=std::getenv("NADOC_TEST_VOLUMES")!=nullptr;
 nadoc_vr::ViewVolumeRecord volume;volume.center=data.normalizationCenter;
 volume.half=glm::vec3(.4F,.6F,.5F)/data.normalizationScale;volume.representation=argv[2];
 GlScene scene(std::move(data),true,{}, {},false);
 scene.volumeGuardsEnabledForTest=std::getenv("NADOC_TEST_LEGACY_VOLUMES")==nullptr;
 std::cout<<"VOLUMES enabled="<<volumes<<" guards="<<scene.volumeGuardsEnabledForTest<<std::endl;scene.enablePreparedStyles();scene.setStyle(rep,Coloring::strand);while(scene.stylePending())scene.pollPreparedStyle();
 GLuint query;glGenQueries(1,&query);
 XrFovf fov{-.94902F,.895626F,.971838F,-.974164F};auto vp=projectionFromFov(fov,kNearMeters,kFarMeters);
 const auto model=glm::translate(glm::mat4(1),glm::vec3(0,0,-2.F))*glm::scale(glm::mat4(1),glm::vec3(2))*glm::rotate(glm::mat4(1),glm::half_pi<float>(),glm::vec3(0,1,0))*glm::translate(glm::mat4(1),glm::vec3(0,0,1.3F));
 const auto samplesEnv=std::getenv("NADOC_TEST_SAMPLES");
 const int samples=samplesEnv?std::clamp(std::atoi(samplesEnv),1,10000):40;
 for(std::string mode:{"idle","selected_idle","translate","rotate"}) {
  scene.setToolPreview({},glm::mat4(1));
  bool selected=mode!="idle";if(selected)scene.setSelectionHighlights({}, {},{owner},{});
  const auto fixed=glm::translate(glm::mat4(1),glm::vec3(.003F,0,0));
  if(selected)scene.setToolPreview({owner},fixed);
  glFinish();std::vector<double> update,draw,gpu,total;
  for(int i=0;i<samples+5;++i) {
   float t=float(i)*.13F;auto transform=fixed;
   if(mode=="translate")transform=glm::translate(glm::mat4(1),glm::vec3(.01F*std::sin(t),0,0));
   if(mode=="rotate")transform=glm::translate(glm::mat4(1),pivot)*glm::rotate(glm::mat4(1),.15F*std::sin(t),glm::vec3(0,1,0))*glm::translate(glm::mat4(1),-pivot);
   auto start=Clock::now();scene.setToolPreview(selected?std::vector<std::string>{owner}:std::vector<std::string>{},transform);auto updated=Clock::now();
   glBeginQuery(GL_TIME_ELAPSED,query);scene.renderShadowMap(model,{{-.577F,.577F,.577F},{0,1,0}});
   glBindFramebuffer(GL_FRAMEBUFFER,0);glViewport(0,0,1852,2056);glDrawBuffer(GL_BACK);
   for(int eye=0;eye<2;++eye){glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT);if(volumes)scene.renderVolumes(vp,model,{},false,{volume});else scene.render(vp,model,{},false);}
   glEndQuery(GL_TIME_ELAPSED);auto submitted=Clock::now();GLuint64 ns;glGetQueryObjectui64v(query,GL_QUERY_RESULT,&ns);auto finished=Clock::now();
   if(i>=5){update.push_back(ms(start,updated));draw.push_back(ms(updated,submitted));gpu.push_back(double(ns)/1e6);total.push_back(ms(start,finished));}
  }
  std::vector<unsigned char> pixels(1852*2056*3);glReadPixels(0,0,1852,2056,GL_RGB,GL_UNSIGNED_BYTE,pixels.data());size_t nonzero=0;for(auto c:pixels)nonzero+=c!=0;assert(nonzero>100);
  std::ofstream out(std::string(argv[4])+"-"+mode+".ppm",std::ios::binary);out<<"P6\n1852 2056\n255\n";out.write(reinterpret_cast<char*>(pixels.data()),pixels.size());
  std::cout<<"RESULT rep="<<argv[2]<<" owner="<<argv[3]<<" mode="<<mode<<" samples="<<update.size()<<" nonzero_bytes="<<nonzero;
  stats("update",update);stats("draw_cpu",draw);stats("draw_gpu",gpu);stats("serial_total",total);std::cout<<std::endl;
 }
 glDeleteQueries(1,&query);assert(glGetError()==GL_NO_ERROR);
 }
 glfwDestroyWindow(window);glfwTerminate();return 0;
}

SceneData previewFixture() {
    SceneData data; data.available.fill(true);
    RepresentationData source;
    ColorSet colors; for (auto& c : colors.values) c = {.35F,.65F,.9F};
    source.points.push_back({"point",{-.18F,.1F,-1.3F},colors,.045F});
    source.points.push_back({"fixed",{.25F,.1F,-1.3F},colors,.035F});
    source.cylinders.push_back({"boundary",{-.18F,.1F,-1.3F},{.25F,.1F,-1.3F},.025F,colors});
    source.halfCylinders.push_back({"half",{-.2F,-.15F,-1.3F},{.2F,-.15F,-1.3F},.035F,colors});
    source.boxes.push_back({"box",{0,0,-1.3F},{.15F,0,0},{0,.08F,0},{0,0,.08F},colors});
    source.ownerHandles.push_back({"moving",{0,0,-1.3F}});
    source.ownerHandles.push_back({"other",{.25F,.1F,-1.3F}});
    source.toolScopeOwnership = {
        {"point",{{"moving",1,1}}}, {"fixed",{{"other",1,1}}},
        {"boundary",{{"moving",1,0},{"other",0,1}}},
        {"half",{{"moving",.25F,.75F}}}, {"box",{{"moving",1,1}}}};
    for (size_t i=0;i<kRepresentationCount;++i) data.representations[i]=source;
    return data;
}
int parity() {
    if(!glfwInit())return 77;
    glfwWindowHint(GLFW_VISIBLE,GLFW_FALSE);glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR,4);glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR,3);
    auto* window=glfwCreateWindow(512,512,"preview parity",nullptr,nullptr);
    if(!window){glfwTerminate();return 77;}
    glfwMakeContextCurrent(window);glEnable(GL_DEPTH_TEST);
    {
    GlScene fast(previewFixture(),true,{}, {},false), reference(previewFixture(),true,{}, {},false);
    reference.disablePackedPreviewForTest();
    reference.volumeGuardsEnabledForTest=false;
    std::vector<nadoc_vr::ViewVolumeRecord> volumes;
    const auto vp=glm::perspective(glm::radians(70.F),1.F,.02F,100.F);
    std::vector<unsigned char> expected(512*512*4),actual(expected.size());
    std::vector<float> expectedDepth(512*512),actualDepth(expectedDepth.size());
    auto capture=[&](GlScene& scene,auto& pixels,auto& depth){
        scene.renderShadowMap(glm::mat4(1),{{-.577F,.577F,.577F},{0,1,0}});
        glBindFramebuffer(GL_FRAMEBUFFER,0);glViewport(0,0,512,512);glDrawBuffer(GL_BACK);
        glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT);scene.renderVolumes(vp,glm::mat4(1),{},false,volumes);
        glReadPixels(0,0,512,512,GL_RGBA,GL_UNSIGNED_BYTE,pixels.data());
        glReadPixels(0,0,512,512,GL_DEPTH_COMPONENT,GL_FLOAT,depth.data());
    };
    auto compare=[&](const char* stage){
        capture(reference,expected,expectedDepth);capture(fast,actual,actualDepth);
        size_t changed=0,visible=0;int maxDelta=0;
        for(size_t i=0;i<actual.size();++i)if(i%4!=3){int delta=std::abs(int(actual[i])-int(expected[i]));changed+=delta>1;maxDelta=std::max(maxDelta,delta);visible+=actual[i]>0;}
        assert(visible>100);
        // Packed glow axes change multiplication order by a few float ULPs.
        // Permit isolated raster edges, never missing geometry or a blank image.
        assert(changed<actual.size()/1000);
        for(size_t i=0;i<actualDepth.size();++i)assert(std::abs(actualDepth[i]-expectedDepth[i])<1e-5F);
        for(float x:{-.2F,0.F,.2F}) {
            nadoc_vr::Ray ray{{x,.1F,0},{0,0,-1}};
            const auto a=fast.pick(ray,glm::mat4(1)),b=reference.pick(ray,glm::mat4(1));
            assert(a.has_value()==b.has_value());
            if(a){assert(a->identity==b->identity);assert(std::abs(a->distance-b->distance)<1e-6F);}
        }
        assert(glGetError()==GL_NO_ERROR);
        std::cout<<"PREVIEW_PARITY stage="<<stage<<" differing_bytes_gt1="<<changed<<" max_delta="<<maxDelta<<std::endl;
    };
    for(auto* scene:{&fast,&reference})scene->setSelectionHighlights({}, {},{"moving"},{});
    assert(fast.hasPackedPreviewForTest());compare("selection");
    for(auto* scene:{&fast,&reference})scene->setSelectionHighlights({}, {},{"missing-owner"},{});
    assert(!fast.hasPackedPreviewForTest());
    for(auto* scene:{&fast,&reference})scene->setToolPreview({"missing-owner"},glm::translate(glm::mat4(1),glm::vec3(.2F,0,0)));
    compare("invalid-owner");
    for(auto* scene:{&fast,&reference})scene->setSelectionHighlights({}, {},{"moving"},{});

    for(float angle:{.15F,-.6F,3.14159265F,0.F}) {
        const auto transform=glm::translate(glm::mat4(1),glm::vec3(.03F,-.02F,-1.3F))*glm::rotate(glm::mat4(1),angle,glm::vec3(0,1,0))*glm::translate(glm::mat4(1),glm::vec3(0,0,1.3F));
        for(auto* scene:{&fast,&reference})scene->setToolPreview({"moving"},transform);
        compare("motion");
    }
    for(auto* scene:{&fast,&reference})scene->setToolPreview({},glm::mat4(1));compare("cancel");
    for(auto* scene:{&fast,&reference})scene->setToolPreview({"moving"},glm::translate(glm::mat4(1),glm::vec3(.04F,0,0)));
    for(auto* scene:{&fast,&reference})assert(scene->acceptToolCommit());compare("commit");
    for(auto* scene:{&fast,&reference})scene->setToolPreview({"moving"},glm::translate(glm::mat4(1),glm::vec3(0,.03F,0)));compare("after-commit");
    for(auto* scene:{&fast,&reference})scene->setStyle(Representation::vdw,Coloring::strand);compare("style-change");
    for(auto* scene:{&fast,&reference})scene->setToolPreview({"other"},glm::translate(glm::mat4(1),glm::vec3(0,-.03F,0)));compare("owner-change");
    for(auto* scene:{&fast,&reference})scene->setToolPreview({},glm::mat4(1));
    for(auto* scene:{&fast,&reference})assert(scene->acceptToolUndo());compare("undo");
    for(auto* scene:{&fast,&reference}){scene->installRepresentation(previewFixture());scene->setStyle(Representation::full,Coloring::strand);}
    compare("scene-replacement");
    assert(fast.volumeUploadsForTest==0);
    nadoc_vr::ViewVolumeRecord volume;volume.center={0,0,0};volume.half={.2F,.2F,2.F};
    for(auto rep:{Representation::full,Representation::stick,Representation::ballstick,Representation::vdw}) {
        for(auto* scene:{&fast,&reference}) {
            scene->setStyle(rep,Coloring::strand);
            scene->setSelectionHighlights({}, {},{"moving"},{});
            scene->setToolPreview({"moving"},glm::translate(glm::mat4(1),glm::vec3(.03F,0,0)));
        }
        volume.representation=representationName(rep);volumes={volume};
        const auto styles=fast.styleApplicationsForTest;
        compare("volume-selected-same-style");
        const auto uploads=fast.volumeUploadsForTest;
        compare("volume-second-eye");
        assert(fast.styleApplicationsForTest==styles && fast.volumeUploadsForTest==uploads);
        volumes[0].center.x+=.1F;compare("volume-moved");
        assert(fast.styleApplicationsForTest==styles && fast.volumeUploadsForTest==uploads+1);
        volumes[0].sides=6;volumes[0].opacity=.5F;compare("volume-hex-opacity");
        auto other=volume;other.representation=rep==Representation::vdw?"full":"vdw";
        other.coloring="cpk";volumes.push_back(other);compare("volume-mixed-styles");
        volumes.clear();compare("volumes-removed");
        volume.enabled=false;volumes={volume};compare("volume-disabled");volume.enabled=true;
    }
    }
    glfwDestroyWindow(window);glfwTerminate();return 0;
}
int originContract() {
    const auto path=std::filesystem::temp_directory_path()/("nadoc-origin-"+std::to_string(getpid())+".nadocvr");
    {
        std::ofstream out(path);
        out << "NADOCVR 16 full strand\nO 0 1 0 -1 0 0 0 0 1\nR full\n"
            << "P origin 0 0 0 .1 1 0 0 1 0 0 1 0 0 1 0 0\n"
            << "P offset 3 7 11 .1 1 0 0 1 0 0 1 0 0 1 0 0\n";
    }
    auto scene=loadScene(path.string(),std::pair(glm::vec3(10,-20,30),.07F));
    std::filesystem::remove(path);
    const auto origin=-scene.normalizationCenter*scene.normalizationScale+glm::vec3(0,0,-kViewDistanceMeters);
    const auto& rep=scene.representations[representationSourceIndex(Representation::full)];
    assert(glm::distance(rep.points[0].position,origin)<1e-6F);
    assert(rep.cylinders.size()==3);
    const std::array<glm::vec3,3> axes{{{0,1,0},{-1,0,0},{0,0,1}}};
    for(size_t i=0;i<3;++i){
        assert(glm::distance(rep.cylinders[i].start,origin)<1e-6F);
        assert(glm::distance(rep.cylinders[i].end-origin,axes[i]*(4*.07F))<1e-6F);
    }
    const auto stage=glm::translate(glm::mat4(1),glm::vec3(1.2F,-.3F,-.8F))
        *glm::toMat4(glm::angleAxis(.5F,glm::vec3(0,1,0)));
    const auto expected=glm::vec3(stage*glm::vec4(0,1.1F,0,1));
    for(auto head:{glm::vec3(2,1.7F,3),glm::vec3(-1,1.2F,-2)}){
        nadoc_vr::SceneManipulator model;
        model.placeAtRoomOrigin(head,glm::quat(glm::vec3(.3F,.8F,-.2F)),stage,origin);
        assert(glm::distance(glm::vec3(model.transform()*glm::vec4(origin,1)),expected)<1e-5F);
        assert(std::abs(model.scale()-2)<1e-6F);
        model.placeAtRoomOrigin(head,glm::quat(1,0,0,0),std::nullopt,origin);
        assert(glm::distance(glm::vec3(model.transform()*glm::vec4(origin,1)),glm::vec3(0,head.y-.35F,0))<1e-5F);
    }
    std::cout << "ORIGIN_CONTRACT desktop frame, normalized origin, room center and fallback passed\n";
    return 0;
}
int main(int argc,char** argv) {
    if(argc==2 && std::string(argv[1])=="--origin")return originContract();
    if(argc==5)return benchmark(argc,argv);
    if(argc!=1)return 2;
    return parity();
}
