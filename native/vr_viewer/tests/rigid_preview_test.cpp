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
 scene.residentPreviewForTest=std::getenv("NADOC_TEST_LEGACY_PREVIEW_SETUP")==nullptr;
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
  const auto firstStarted=Clock::now();
  if(selected)scene.setToolPreview({owner},fixed);
  std::cout<<"FIRST_PREVIEW rep="<<argv[2]<<" owner="<<argv[3]<<" mode="<<mode
      <<" elapsed_ms="<<ms(firstStarted,Clock::now())<<std::endl;
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
    ColorSet colors; for (size_t i=0;i<colors.values.size();++i) colors.values[i] = {.35F+.03F*i,.65F,.9F};
    source.points.push_back({"point",{-.18F,.1F,-1.3F},colors,.045F});
    source.points.push_back({"fixed",{.25F,.1F,-1.3F},colors,.035F});
    source.points.push_back({"zero",{.1F,-.25F,-1.3F},colors,.025F});
    source.cylinders.push_back({"boundary",{-.18F,.1F,-1.3F},{.25F,.1F,-1.3F},.025F,colors});
    source.halfCylinders.push_back({"half",{-.2F,-.15F,-1.3F},{.2F,-.15F,-1.3F},.035F,colors});
    source.boxes.push_back({"box",{0,0,-1.3F},{.15F,0,0},{0,.08F,0},{0,0,.08F},colors});
    source.ownerHandles.push_back({"moving",{0,0,-1.3F}});
    source.ownerHandles.push_back({"other",{.25F,.1F,-1.3F}});
    source.toolScopeOwnership = {
        {"point",{{"moving",1,1}}}, {"fixed",{{"other",1,1}}},
        {"zero",{{"moving",0,0}}},
        {"boundary",{{"moving",1,0},{"other",0,1}}},
        {"half",{{"moving",.25F,.75F}}}, {"box",{{"moving",1,1}}}};
    source.ownerAliases={{"point",{"moving"}},{"boundary",{"moving"}},
        {"half",{"moving"}},{"zero",{"moving"}}};
    for (size_t i=0;i<kRepresentationCount;++i) {
        data.representations[i]=source;
        auto index=std::make_shared<SourceIndex>();index->rebuild(data.representations[i]);
        data.prepared[i]=prepareStaticRepresentation(data.representations[i],static_cast<Representation>(i),index);
    }
    return data;
}
#include "motion_detail_render.inc"

int parity() {
    if(!glfwInit())return 77;
    glfwWindowHint(GLFW_VISIBLE,GLFW_FALSE);glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR,4);glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR,3);
    auto* window=glfwCreateWindow(512,512,"preview parity",nullptr,nullptr);
    if(!window){glfwTerminate();return 77;}
    glfwMakeContextCurrent(window);glEnable(GL_DEPTH_TEST);
    {
    GlScene fast(previewFixture(),true,{}, {},false);
    fast.enablePreparedStyles();
    fast.setStyle(Representation::full,Coloring::strand);
    while(fast.stylePending())fast.pollPreparedStyle();
    GlScene reference(previewFixture(),true,{}, {},false);
    reference.staticSnapHighlightsForTest=false;
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
        while(fast.stylePending())fast.pollPreparedStyle();
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
    // The prepared first-grab path must match the general renderer for each
    // supported style, including duplicate aliases and explicit zero weights.
    for(auto rep:{Representation::full,Representation::stick,Representation::ballstick,Representation::vdw}) {
        for(auto color:{Coloring::strand,Coloring::cpk}) {
            for(auto* scene:{&fast,&reference})scene->setStyle(rep,color);
            compare("resident-before-grab");
            const auto initialPixels=actual;
            const auto styles=fast.styleApplicationsForTest;
            for(auto* scene:{&fast,&reference})scene->setToolPreview({"moving"},
                glm::translate(glm::mat4(1),glm::vec3(.03F,.02F,0)));
            assert(fast.hasPackedPreviewForTest() && fast.styleApplicationsForTest==styles);
            compare("resident-first-grab");assert(actual!=initialPixels);
            for(auto* scene:{&fast,&reference})scene->setToolPreview({},glm::mat4(1));
            compare("resident-cancel");assert(actual==initialPixels);
            // Restoring a resident must not restore preview-modified buffers.
            for(auto* scene:{&fast,&reference})scene->setStyle(rep,color);
            compare("resident-cache-restored");assert(actual==initialPixels);
            for(auto* scene:{&fast,&reference})scene->setToolPreview({"other"},
                glm::translate(glm::mat4(1),glm::vec3(-.03F,0,0)));
            compare("resident-other-owner");
            for(auto* scene:{&fast,&reference})assert(scene->acceptToolCommit());
            compare("resident-commit");
            for(auto* scene:{&fast,&reference})assert(scene->acceptToolUndo());
            compare("resident-undo");assert(actual==initialPixels);
        }
    }
    for(auto* scene:{&fast,&reference})scene->setStyle(Representation::full,Coloring::strand);
    compare("resident-tests-restored");
    const auto beforeHover=fast.styleApplicationsForTest;
    for(auto* scene:{&fast,&reference})scene->setSelectionHighlights({"moving"}, {},{},{});
    compare("hover-owner");
    for(auto* scene:{&fast,&reference})scene->setSelectionHighlights({}, {"fixed"},{},{});
    compare("hover-identity");
    for(auto* scene:{&fast,&reference})scene->setSelectionHighlights({}, {},{},{});
    compare("hover-cleared");
    assert(fast.styleApplicationsForTest==beforeHover);
    const auto unselectedPixels=actual;
    const auto unselectedDepth=actualDepth;
    for(auto* scene:{&fast,&reference})scene->setSelectionHighlights({}, {},{"moving"},{});
    assert(fast.styleApplicationsForTest==beforeHover);compare("selection");
    size_t tinted=0;
    for(size_t i=0;i<actual.size();++i) tinted+=actual[i]!=unselectedPixels[i];
    assert(tinted>100); // A matching pair of unhighlighted scenes must not pass.
    assert(actualDepth==unselectedDepth); // Selection must not alter design depth/picking.
    for(auto* scene:{&fast,&reference})scene->setSelectionHighlights({}, {},{},{});
    compare("deselection-restores-pixels");assert(actual==unselectedPixels);
    for(auto* scene:{&fast,&reference})scene->setSelectionHighlights({}, {},{"moving"},{});
    const auto beforeSelectedHover=fast.styleApplicationsForTest;
    for(auto* scene:{&fast,&reference})scene->setSelectionHighlights({"moving"}, {},{"moving"},{});
    compare("hover-subsumed-by-selection");
    assert(fast.styleApplicationsForTest==beforeSelectedHover);
    for(auto* scene:{&fast,&reference})scene->setSelectionHighlights({"other"}, {"half"},{"moving"},{});
    compare("hover-with-selection");
    assert(fast.styleApplicationsForTest==beforeSelectedHover);
    const auto beforeFirstPreview=fast.styleApplicationsForTest;
    for(auto* scene:{&fast,&reference})scene->setToolPreview({"moving"},glm::translate(glm::mat4(1),glm::vec3(.02F,.03F,0)));
    assert(fast.styleApplicationsForTest==beforeFirstPreview);
    compare("hover-weighted-preview");
    for(auto* scene:{&fast,&reference})scene->setToolPreview({},glm::mat4(1));
    for(auto* scene:{&fast,&reference})scene->setSelectionHighlights({}, {},{"moving"},{});
    compare("hover-with-selection-cleared");
    for(auto* scene:{&fast,&reference})scene->setSelectionHighlights({}, {},{"missing-owner"},{});
    assert(!fast.hasPackedPreviewForTest());
    for(auto* scene:{&fast,&reference})scene->setToolPreview({"missing-owner"},glm::translate(glm::mat4(1),glm::vec3(.2F,0,0)));
    compare("invalid-owner");
    for(auto* scene:{&fast,&reference})scene->setSelectionHighlights({}, {},{"moving"},{});

    for(int repeat=0;repeat<2;++repeat) {
        const auto delta=glm::translate(glm::mat4(1),glm::vec3(.04F,.02F,0));
        const auto styles=fast.styleApplicationsForTest;
        fast.setMovePointPreview({"moving"},delta);
        assert(fast.styleApplicationsForTest==styles);
        reference.setToolPreview({"moving"},delta);
        for(auto* scene:{&fast,&reference})assert(scene->acceptToolCommit());
        assert(fast.movePointCount()==0);
        compare("point-preview-commit");
    }
    for(auto* scene:{&fast,&reference})assert(scene->acceptToolUndo());
    compare("point-preview-undo");
    for(float angle:{.15F,-.6F,3.14159265F,0.F}) {
        const auto transform=glm::translate(glm::mat4(1),glm::vec3(.03F,-.02F,-1.3F))*glm::rotate(glm::mat4(1),angle,glm::vec3(0,1,0))*glm::translate(glm::mat4(1),glm::vec3(0,0,1.3F));
        for(auto* scene:{&fast,&reference})scene->setToolPreview({"moving"},transform);
        compare("motion");
    }
    for(auto* scene:{&fast,&reference})scene->setToolPreview({},glm::mat4(1));compare("cancel");
    for(auto* scene:{&fast,&reference})scene->setToolPreview({"moving"},glm::translate(glm::mat4(1),glm::vec3(.04F,0,0)));
    const auto stylesBeforeCommit = fast.styleApplicationsForTest;
    for(auto* scene:{&fast,&reference})assert(scene->acceptToolCommit());compare("commit");
    assert(fast.styleApplicationsForTest == stylesBeforeCommit);
    for(auto* scene:{&fast,&reference})assert(scene->acceptToolUndo());compare("packed-undo");
    assert(fast.styleApplicationsForTest == stylesBeforeCommit);
    for(auto* scene:{&fast,&reference})scene->setToolPreview({"moving"},glm::translate(glm::mat4(1),glm::vec3(.04F,0,0)));
    for(auto* scene:{&fast,&reference})assert(scene->acceptToolCommit());compare("recommit-after-undo");
    for(auto* scene:{&fast,&reference})scene->setToolPreview({"moving"},glm::translate(glm::mat4(1),glm::vec3(0,.03F,0)));compare("after-commit");
    for(auto* scene:{&fast,&reference})assert(scene->acceptToolUndo());compare("packed-undo-with-preview");
    assert(fast.styleApplicationsForTest == stylesBeforeCommit);
    for(auto* scene:{&fast,&reference})assert(scene->acceptToolCommit());compare("commit-pending-after-undo");
    for(auto* scene:{&fast,&reference})scene->setToolPreview({"moving"},glm::translate(glm::mat4(1),glm::vec3(.02F,0,0)));
    for(auto* scene:{&fast,&reference})assert(scene->acceptToolCommit());compare("second-commit-bakes-previous-layer");
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
        model.placeAtRoomOrigin(head,glm::quat(glm::vec3(.3F,.8F,-.2F)),stage,origin,scene.sourceAxes);
        assert(glm::distance(glm::vec3(model.transform()*glm::vec4(origin,1)),expected)<1e-5F);
        assert(std::abs(model.scale()-2)<1e-6F);
        model.placeAtRoomOrigin(head,glm::quat(1,0,0,0),std::nullopt,origin,scene.sourceAxes);
        assert(glm::distance(glm::vec3(model.transform()*glm::vec4(origin,1)),glm::vec3(0,head.y-.35F,0))<1e-5F);
    }
    // Desktop orbit (including pitch/roll) must not tilt the authored floor
    // plane. Check actual loaded source axes as well as arbitrary camera bases.
    for(const auto basis:{scene.sourceAxes,glm::mat3(1),
            glm::mat3_cast(glm::quat(glm::vec3(.7F,-1.1F,.4F)))}) {
        for(const auto angles:{glm::vec3(0),glm::vec3(.3F,.8F,-.2F),
                glm::vec3(-.6F,-1.4F,.5F)}) {
            const auto head=glm::quat(angles);
            const auto forward=head*glm::vec3(0,0,-1);
            const auto heading=glm::normalize(glm::vec3(forward.x,0,forward.z));
            for(const auto floor:{std::optional(stage),std::optional<glm::mat4>()}) {
                nadoc_vr::SceneManipulator model;
                model.placeAtRoomOrigin({2,1.7F,3},head,floor,origin,basis);
                const auto world=glm::mat3(model.transform())*basis/model.scale();
                assert(glm::distance(world[1],glm::vec3(0,1,0))<1e-5F);
                assert(std::abs(world[0].y)<1e-5F && std::abs(world[2].y)<1e-5F);
                assert(glm::distance(-world[2],heading)<1e-5F);
                assert(glm::distance(world[0],glm::cross(heading,glm::vec3(0,1,0)))<1e-5F);
                const auto target=floor?expected:glm::vec3(0,1.35F,0);
                assert(glm::distance(glm::vec3(model.transform()*glm::vec4(origin,1)),target)<1e-5F);
            }
        }
    }
    std::cout << "ORIGIN_CONTRACT desktop frame, normalized origin, room center and fallback passed\n";
    return 0;
}
int orientationRender(const std::filesystem::path& output) {
    if(!glfwInit())return 77;
    glfwWindowHint(GLFW_VISIBLE,GLFW_FALSE);
    glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR,4);glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR,3);
    auto* window=glfwCreateWindow(512,512,"initial orientation",nullptr,nullptr);
    if(!window){glfwTerminate();return 77;}
    glfwMakeContextCurrent(window);glEnable(GL_DEPTH_TEST);
    std::filesystem::create_directories(output);
    const glm::vec3 origin(0,0,-1.3F),head(0,1.7F,1.5F);
    const auto tilted=glm::mat3_cast(glm::quat(glm::vec3(.7F,-1.1F,.4F)));
    const auto vp=glm::perspective(glm::radians(60.F),1.F,.02F,100.F)
        *glm::lookAt(head,glm::vec3(0,1.1F,0),glm::vec3(0,1,0));
    auto capture=[&](const char* name,glm::mat3 basis,bool correct) {
        SceneData data;data.available.fill(true);
        auto& rep=data.representations[representationSourceIndex(Representation::full)];
        ColorSet colors;colors.values.fill({.3F,.7F,.9F});
        // Explicit box axes keep tessellation identical across export bases;
        // cylinders choose radial facets in export space and change shading.
        // A flat, asymmetric ladder in authored XZ exposes desktop-camera tilt.
        for(int i=0;i<7;++i){
            const float x=-.18F+.06F*i;
            rep.boxes.push_back({"helix"+std::to_string(i),
                origin+basis*glm::vec3(x,0,-.05F),basis*glm::vec3(.015F,0,0),
                basis*glm::vec3(0,.015F,0),basis*glm::vec3(0,0,.2F),colors});
        }
        GlScene scene(std::move(data),true,{}, {},false);
        nadoc_vr::SceneManipulator model;
        model.placeAtRoomOrigin(head,glm::quat(1,0,0,0),glm::mat4(1),origin,correct?basis:glm::mat3(1));
        scene.renderShadowMap(model.transform(),{{-.577F,.577F,.577F},{0,1,0}});
        glBindFramebuffer(GL_FRAMEBUFFER,0);glViewport(0,0,512,512);glDrawBuffer(GL_BACK);
        glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT);
        scene.render(vp,model.transform(),{},false);
        std::vector<unsigned char> rgb(512*512*3);
        glReadPixels(0,0,512,512,GL_RGB,GL_UNSIGNED_BYTE,rgb.data());
        assert(std::count_if(rgb.begin(),rgb.end(),[](auto c){return c>0;})>1000);
        std::ofstream image(output/(std::string(name)+".ppm"),std::ios::binary);
        image<<"P6\n512 512\n255\n";
        for(int y=511;y>=0;--y)image.write(reinterpret_cast<char*>(rgb.data()+y*512*3),512*3);
        assert(glGetError()==GL_NO_ERROR);
        return rgb;
    };
    const auto reference=capture("canonical",glm::mat3(1),true);
    const auto before=capture("before",tilted,false);
    const auto after=capture("after",tilted,true);
    size_t corrected=0,uncorrected=0;
    for(size_t i=0;i<reference.size();++i){
        corrected+=std::abs(int(reference[i])-int(after[i]))>2;
        uncorrected+=std::abs(int(reference[i])-int(before[i]))>2;
    }
    assert(corrected<reference.size()/1000);
    assert(uncorrected>reference.size()/100);
    std::cout<<"ORIENTATION_RENDER corrected_differing_bytes="<<corrected
        <<" old_differing_bytes="<<uncorrected<<" evidence="<<output<<'\n';
    glfwDestroyWindow(window);glfwTerminate();return 0;
}
int selectionRender(const std::filesystem::path& output) {
    if(!glfwInit())return 77;
    glfwWindowHint(GLFW_VISIBLE,GLFW_FALSE);
    glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR,4);glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR,3);
    auto* window=glfwCreateWindow(512,512,"selection tint",nullptr,nullptr);
    if(!window){glfwTerminate();return 77;}
    glfwMakeContextCurrent(window);glEnable(GL_DEPTH_TEST);
    std::filesystem::create_directories(output);
    {
        GlScene scene(previewFixture(),true,{}, {},false);
        const auto model=glm::translate(glm::mat4(1),glm::vec3(0,0,-1.3F))
            *glm::mat4_cast(glm::quat(glm::vec3(.3F,.5F,.4F)))
            *glm::translate(glm::mat4(1),glm::vec3(0,0,1.3F));
        auto capture=[&](const char* name) {
            glViewport(0,0,512,512);glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT);
            scene.render(glm::perspective(glm::radians(70.F),1.F,.02F,100.F),model,{},false);
            std::vector<unsigned char> rgb(512*512*3);
            glReadPixels(0,0,512,512,GL_RGB,GL_UNSIGNED_BYTE,rgb.data());
            std::ofstream image(output/(std::string(name)+".ppm"),std::ios::binary);
            image<<"P6\n512 512\n255\n";
            for(int y=511;y>=0;--y)image.write(reinterpret_cast<char*>(rgb.data()+y*512*3),512*3);
            return rgb;
        };
        const auto before=capture("unselected");
        scene.setSelectionHighlights({}, {}, {"moving"}, {});
        const auto selected=capture("selected");
        size_t visible=0,changed=0;
        for(size_t i=0;i<before.size();i+=3) {
            const bool a=before[i] || before[i+1] || before[i+2];
            const bool b=selected[i] || selected[i+1] || selected[i+2];
            assert(a==b); // No corner brackets or other pixels outside the part.
            visible+=b;changed+=before[i]!=selected[i] || before[i+1]!=selected[i+1] || before[i+2]!=selected[i+2];
        }
        assert(visible>100 && changed>100); // Selection tint must remain visible.
        scene.setSelectionHighlights({}, {}, {}, {});
        assert(capture("cleared")==before);
        assert(glGetError()==GL_NO_ERROR);
        std::cout<<"SELECTION_RENDER selected_pixels="<<visible<<" tinted_pixels="<<changed<<" no outline pixels\n";
    }
    glfwDestroyWindow(window);glfwTerminate();return 0;
}
int main(int argc,char** argv) {
    if(argc==3 && std::string(argv[1])=="--selection-render")return selectionRender(argv[2]);
    if(argc==3 && std::string(argv[1])=="--orientation-render")return orientationRender(argv[2]);
    if(argc==2 && std::string(argv[1])=="--motion-detail")return motionDetailRender() || motionDetailRender(true);
    if(argc==2 && std::string(argv[1])=="--origin")return originContract();
    if(argc==5)return benchmark(argc,argv);
    if(argc!=1)return 2;
    return parity();
}
