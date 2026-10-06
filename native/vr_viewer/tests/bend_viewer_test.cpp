// Exercise the production trigger, wheel, panel, transport and GL guide paths.
#define NADOC_SCRYWRITE_TESTING
#define main nadoc_viewer_entry_point
#include "../src/main.cpp"
#undef main
#include <cassert>
namespace {
struct TestSocketDirectory {
    std::filesystem::path path;
    TestSocketDirectory() {
        char pattern[]="/tmp/nadoc-bend-sockets-XXXXXX";
        const auto* created=::mkdtemp(pattern);
        if(!created)throw std::runtime_error("Cannot create Bend test socket directory");
        path=created;
    }
    ~TestSocketDirectory() {
        std::error_code ignored;
        std::filesystem::remove_all(path,ignored);
    }
};
struct LiveViewerTest {
    static std::string publishedEvent(const Viewer& v) {
        const auto prefix="{\"sequence\":"+std::to_string(v.eventSequence_)+",";
        const auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(5);
        do {
            std::ifstream event(v.eventPath_);
            std::string json((std::istreambuf_iterator<char>(event)),{});
            if(json.starts_with(prefix))return json;
            std::this_thread::sleep_for(std::chrono::milliseconds(1));
        } while(std::chrono::steady_clock::now()<deadline);
        throw std::runtime_error("Bend event publication timed out at sequence "+
            std::to_string(v.eventSequence_)+" (writer failures "+
            std::to_string(v.eventWriter_.failures())+")");
    }
    static void clusters(const std::string& directory,const std::filesystem::path& sockets) {
        Viewer v(SceneData{},directory+"/cluster-events.json");
        v.liveSocket_.open((sockets/"clusters.sock").string());
        SceneData data;data.available.fill(true);RepresentationData source;ColorSet colors;
        for(auto& c:colors.values)c={.3F,.7F,1};
        source.points={{"nuc:near",{0,0,-.5F},colors,.01F},{"nuc:far",{1,0,-2},colors,.01F}};
        source.ownerHandles={{"near",{0,0,-.5F}},{"far",{1,0,-2}}};
        source.ownerAliases={{"nuc:near",{"near"}},{"nuc:far",{"far"}}};
        for(auto& rep:data.representations)rep=source;
        v.glScene_=std::make_unique<GlScene>(std::move(data));
        assert(v.glScene_->belongsToSelection("nuc:near",{"near","domain:other"}));
        assert(v.glScene_->belongsToSelection("nuc:far",{"near","far"}));
        assert(!v.glScene_->belongsToSelection("nuc:far",{"near"}));
        v.witnessObserverPosition_={0,0,0};v.selectedIdentity_="nuc:near";
        v.selectedSelectionKind_="cluster";v.selectedOwnerTokens_={"near"};
        v.activateSidebarAction("tool:bend",1);
        assert(v.bendPanel_.clusterLabel=="Selected cluster" && v.bendPanel_.defaultPlanes);
        assert(v.bendPickExtent_=="a" && !v.bendPickPosition_ && v.activePlanePickSequence_);
        v.planeFeedbackPath_=directory+"/plane-feedback.txt";
        auto acknowledge=[&](const std::string& slot,int bp) {
            {std::ofstream f(v.planeFeedbackPath_);f<<"NADOCVR_PLANE_FEEDBACK 2 "<<v.activePlanePickSequence_<<' '<<v.toolConfigSequence_
                <<" 1 resolved "<<slot<<' '<<v.selectedSelectionKind_<<' '<<v.selectedIdentity_<<' '<<v.selectedIdentity_<<' '<<bp<<" 0 0 "<<bp*.334<<" 0 0 1 2\n";}
            v.planeFeedbackPollFrame_=2;v.pollPlanePickFeedback();
        };
        acknowledge("a",-12);assert(v.bendPickExtent_=="b" && v.toolConfig_.planeABp()==-12);
        acknowledge("b",104);assert(v.bendReady() && !v.bendPanel_.defaultPlanes && v.toolConfig_.planeBBp()==104);
        v.activateSidebarAction("bend:cluster",1);assert(v.bendPanel_.selecting);
        assert(!v.bendReady() && !v.planeGuides_[0]);
        v.selectedIdentity_="selection:test:2";v.selectedSelectionKind_="selection";
        v.selectedOwnerTokens_={v.selectedIdentity_};
        v.committedSelectionOwnerTokens_={"%5B%22cluster%22%2C%22one%22%5D","%5B%22strand%22%2C%22two%22%5D","%5B%22domain%22%2C%22three%22%2C0%5D"};
        (void)v.toolConfig_.bind(nadoc_vr::ToolMode::bend,v.selectedIdentity_,v.selectedSelectionKind_,v.selectedOwnerTokens_);
        v.activateSidebarAction("bend:cluster",1);
        assert(!v.bendPanel_.selecting && v.bendPanel_.defaultPlanes);
        assert(v.toolConfig_.targetIdentity()=="selection:test:2");
        // Switching tools preserves the complete set and requests aggregate bounds.
        v.activateSidebarAction("tool:twist",1);
        assert(v.selectedIdentity_=="selection:test:2" && v.bendPanel_.defaultPlanes);
        assert(v.bendPanel_.clusterLabel=="1 clusters / 1 strands / 1 domains");
        assert(v.toolConfig_.targetSelectionKind()=="selection");
        acknowledge("a",20);acknowledge("b",80);
        assert(v.bendReady());
        v.activateSidebarAction("twist:more",1);
        assert(v.toolConfig_.twistAmount()==95);
        v.activateSidebarAction("twist:target",1);assert(v.bendPanel_.selecting);
        const auto selectSequence=v.selectSequence_;
        v.activateSidebarAction("twist:zero",1);
        assert(v.selectSequence_==selectSequence+1 && v.lastSelectIdentities_.empty());
        v.activateSidebarAction("twist:target",1);assert(!v.bendPanel_.selecting);
        acknowledge("a",20);acknowledge("b",80);assert(v.bendReady());
        auto event=publishedEvent(v);
        assert(event.find("selection:test:2")!=std::string::npos);
        v.activateSidebarAction("tool:bend",1);
        acknowledge("a",20);acknowledge("b",80);
        assert(v.bendReady());
        v.applyBendAdjustment(60,30);
        event=publishedEvent(v);
        assert(event.find("selection:test:2")!=std::string::npos);
        assert(event.find("bend_endpoints")==std::string::npos);
        assert(v.toolConfig_.bendAngleDegrees()==60);
        v.activateSidebarAction("bend:confirm",1);
        assert(v.toolShell_.executionPending());

    }
    static void run(const std::string& directory) {
        TestSocketDirectory sockets;
        clusters(directory,sockets.path);
        Viewer v(SceneData{},directory+"/events.json");
        v.liveSocket_.open((sockets.path/"test.sock").string()); // Suppress physical haptics.
        SceneData data;data.available.fill(true);
        v.glScene_=std::make_unique<GlScene>(std::move(data));
        v.selectedIdentity_="test";v.selectedSelectionKind_="cluster";v.selectedOwnerTokens_={"owner"};
        v.activateSidebarAction("tool:bend",1);
        assert(v.bendPanel_.active && !v.latticeOpen_);
        assert(v.sidebarMenus_.menus[1].customTab->key=="bend");
        v.activateSidebarAction("bend:plane1",1);
        assert(v.activePlanePickSequence_>0 && !v.bendPanel_.pickSlot);
        v.clearPlanePick();v.bendPanel_.defaultPlanes=false;
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
        // Default mode grabs the plane surface with a remote ray; it never bends.
        v.hands_[1].valid=true;v.hands_[1].position={0,0,1};v.hands_[1].orientation=glm::quat(1,0,0,0);
        std::array<bool,2> sliding{};v.processBendPlanes(sliding,false);
        assert(v.bendPanel_.planeHover[1]==1 && v.bendPanel_.beamEnd[1]);
        v.triggerClicked_[1]=true;v.triggerPressed_[1]=true;v.processBendPlanes(sliding,false);
        assert(v.bendPanel_.planeHand==1 && !v.bendPanel_.hand);
        v.triggerClicked_[1]=false;v.hands_[1].position.z-=.1F;sliding.fill(false);v.processBendPlanes(sliding,false);
        assert(v.activePlanePickSequence_ && v.bendPickPosition_ && v.planePickSlot_=="b");
        assert(v.toolConfig_.planeBBp()==100 && !v.bendPanel_.posed);
        v.triggerPressed_[1]=false;v.processBendPlanes(sliding,false);v.clearPlanePick();
        v.hands_[1].position={2,0,1};sliding.fill(false);v.processBendPlanes(sliding,false);
        assert(!v.bendPanel_.planeHover[1] && !v.bendPanel_.beamEnd[1]);
        v.activateSidebarAction("bend:manual",1);assert(v.bendPanel_.manual);
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
        // Event snapshots publish asynchronously; inspect the current sequence,
        // after every queued plane/drag update has reached the atomic writer.
        const auto json=publishedEvent(v);
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
        auto aimWheel=[&](const std::string& field) {
            const auto& menu=v.sidebarMenus_.menus[1];const auto controls=menu.controls();
            const auto c=std::find_if(controls.begin(),controls.end(),[&](const auto& c){return c.id=="bend:"+field+"-wheel";});
            const auto xy=(c->bounds.minimum+c->bounds.maximum)*.5F;
            v.hands_[1].position=menu.placement.worldPoint({xy.x,xy.y,.2F});
            const auto normal=glm::normalize(menu.placement.worldPoint({0,0,1})-menu.placement.worldPoint({0,0,0}));
            v.hands_[1].orientation=glm::rotation(glm::vec3(0,0,-1),-normal);
        };
        aimWheel("direction");
        v.activateSidebarAction("bend:direction",1);assert(!v.bendPanel_.wheelHand);
        v.activateSidebarAction("bend:direction-wheel",1);
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
        // Pause before release so this precision check has no flick momentum.
        for(int i=0;i<30;++i)v.processBendWheel(blocked);
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
        v.sidebarMenus_.menus[1].focus.id="bend:direction-less";
        v.sidebarMenus_.menus[1].navigate({1,0});
        assert(v.sidebarMenus_.menus[1].focus.id=="bend:direction-more");
        const auto oldAngle=v.toolConfig_.bendAngleDegrees();
        v.triggerPressed_[1]=true;
        aimWheel("angle");v.activateSidebarAction("bend:angle-wheel",1);
        const auto& placement=v.sidebarMenus_.menus[1].placement;
        auto local=placement.localPoint(v.hands_[1].position);local.y+=.045F;
        v.hands_[1].position=placement.worldPoint(local);blocked.fill(false);v.processBendWheel(blocked);
        assert(blocked[1] && v.toolConfig_.bendAngleDegrees()==std::round(oldAngle)+1);
        // Pause before release so this precision check has no flick momentum.
        for(int i=0;i<30;++i)v.processBendWheel(blocked);
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
        // Flicks coast after trigger release and eventually settle; confirm waits.
        aimWheel("direction");v.triggerPressed_[1]=true;
        v.activateSidebarAction("bend:direction-wheel",1);
        local=placement.localPoint(v.hands_[1].position);local.y+=.12F;
        v.hands_[1].position=placement.worldPoint(local);blocked.fill(false);v.processBendWheel(blocked);
        const auto flickDirection=v.toolConfig_.bendDirectionDegrees();
        v.triggerPressed_[1]=false;v.processBendWheel(blocked);assert(!v.bendReady());
        for(int i=0;i<1000;++i)v.processBendWheel(blocked);
        assert(v.toolConfig_.bendDirectionDegrees()!=flickDirection && v.bendReady());
        assert(v.toolConfig_.planeABp()==0 && v.toolConfig_.planeBBp()==100);
        // Focus loss stops a spinning wheel without discarding the draft.
        v.bendPanel_.wheels[1].begin(0);(void)v.bendPanel_.wheels[1].drag(.1F,.01F);
        v.bendPanel_.wheelHand=1;const auto savedAngle=v.toolConfig_.bendAngleDegrees();
        v.suspendControllerInput();assert(!v.bendPanel_.wheelHand && !v.bendPanel_.wheels[1].moving());
        assert(v.bendReady() && v.toolConfig_.bendAngleDegrees()==savedAngle);
        // Render the real panel with a mixed-selection summary and raised wheels.
        v.bendPanel_.describeSelection("selection", {"%5B%22cluster%22%2C%22one%22%5D", "%5B%22strand%22%2C%22two%22%5D", "%5B%22domain%22%2C%22three%22%2C0%5D"});
        v.refreshExtrudePanel();
        GLuint panelFbo=0,panelTexture=0;
        glGenFramebuffers(1,&panelFbo);glBindFramebuffer(GL_FRAMEBUFFER,panelFbo);
        glGenTextures(1,&panelTexture);glBindTexture(GL_TEXTURE_2D,panelTexture);
        glTexImage2D(GL_TEXTURE_2D,0,GL_RGB8,800,1000,0,GL_RGB,GL_UNSIGNED_BYTE,nullptr);
        glFramebufferTexture2D(GL_FRAMEBUFFER,GL_COLOR_ATTACHMENT0,GL_TEXTURE_2D,panelTexture,0);
        assert(glCheckFramebufferStatus(GL_FRAMEBUFFER)==GL_FRAMEBUFFER_COMPLETE);glDisable(GL_DEPTH_TEST);
        std::vector<Vertex> panelLines;
        auto panelLine=[&](auto a,auto b,auto c){panelLines.push_back({a,c,1});panelLines.push_back({b,c,1});};
        auto& panel=v.sidebarMenus_.menus[1];
        panel.draw([&](auto a,auto b,auto c){panelLine(panel.placement.worldPoint(a),panel.placement.worldPoint(b),c);},[](auto,auto){});
        const auto savedPlanes=v.planeGuides_;v.planeGuides_.fill(std::nullopt);
        v.drawBend(panelLine);v.planeGuides_=savedPlanes;
        const auto centerPanel=panel.placement.worldPoint({0,0,0});
        const auto eyePanel=panel.placement.worldPoint({.10F,0,2});
        const auto upPanel=glm::normalize(panel.placement.worldPoint({0,1,0})-centerPanel);
        const auto panelVP=glm::ortho(-.36F,.36F,-.45F,.45F,.01F,10.F)*glm::lookAt(eyePanel,centerPanel,upPanel);
        glViewport(0,0,800,1000);glClearColor(.025F,.03F,.04F,1);glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT);
        v.glScene_->renderGuides(panelVP,panelLines);
        v.solidWheels_.render(panelVP);
        std::vector<unsigned char> panelPixels(800*1000*3);glReadPixels(0,0,800,1000,GL_RGB,GL_UNSIGNED_BYTE,panelPixels.data());
        std::ofstream panelPPM(directory+"/bend-panel.ppm",std::ios::binary);panelPPM<<"P6\n800 1000\n255\n";
        for(int y=999;y>=0;--y)panelPPM.write(reinterpret_cast<const char*>(panelPixels.data()+y*800*3),800*3);
        std::cerr<<panel.audit.summary()<<std::endl;assert(panel.audit.valid());
        glBindFramebuffer(GL_FRAMEBUFFER,0);glDeleteFramebuffers(1,&panelFbo);glDeleteTextures(1,&panelTexture);
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
