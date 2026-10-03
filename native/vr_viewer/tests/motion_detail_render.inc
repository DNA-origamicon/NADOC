// Included after previewFixture; compare identical poses with only lighting LOD.
int motionDetailRender(bool coarse=false) {
    if(!glfwInit())return 77;
    glfwWindowHint(GLFW_VISIBLE,GLFW_FALSE);glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR,4);glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR,3);
    auto* window=glfwCreateWindow(512,512,"motion lighting",nullptr,nullptr);
    if(!window){glfwTerminate();return 77;}
    glfwMakeContextCurrent(window);glEnable(GL_DEPTH_TEST);
    {
        setenv("NADOC_VR_MOTION_MESH",coarse?"1":"0",1);
        setenv("NADOC_VR_MOTION_DETAIL","0",1);GlScene full(previewFixture(),true,{}, {},false);
        setenv("NADOC_VR_MOTION_DETAIL","1",1);GlScene moving(previewFixture(),true,{}, {},false);
        const auto transform=glm::translate(glm::mat4(1),glm::vec3(.03F,.02F,0));
        const auto vp=glm::perspective(glm::radians(70.F),1.F,.02F,100.F);
        auto capture=[&](GlScene& scene,std::vector<unsigned char>& pixels,std::vector<float>& depth) {
            scene.renderShadowMap(glm::mat4(1),{{-.577F,.577F,.577F},{0,1,0}});
            glBindFramebuffer(GL_FRAMEBUFFER,0);glViewport(0,0,512,512);glClearColor(0,0,0,1);
            glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT);scene.render(vp,glm::mat4(1),{});
            glReadPixels(0,0,512,512,GL_RGBA,GL_UNSIGNED_BYTE,pixels.data());
            glReadPixels(0,0,512,512,GL_DEPTH_COMPONENT,GL_FLOAT,depth.data());
        };
        std::vector<unsigned char> expected(512*512*4),low(expected.size()),restored(expected.size());
        std::vector<float> a(512*512),b(a.size()),c(a.size());
        for(auto* scene:{&full,&moving})scene->setToolPreview({"moving"},transform);
        capture(full,expected,a);capture(moving,low,b);
        assert(moving.motionDetailReduced());assert(expected!=low);if(!coarse)assert(a==b);else assert(a!=b);
        if(const auto* directory=std::getenv("NADOC_TEST_MOTION_IMAGES")) {
            std::filesystem::create_directories(directory);
            for(auto [name,pixels]:{std::pair{"full",&expected},std::pair{"motion",&low}}) {
                std::ofstream out(std::filesystem::path(directory)/(std::string(name)+(coarse?"-coarse.ppm":".ppm")),std::ios::binary);
                out<<"P6\n512 512\n255\n";
                for(int y=511;y>=0;--y)for(int x=0;x<512;++x)out.write(reinterpret_cast<const char*>(pixels->data()+(y*512+x)*4),3);
            }
        }
        for(float x:{-.2F,0.F,.2F}) {
            const nadoc_vr::Ray ray{{x,.1F,0},{0,0,-1}};
            auto p=full.pick(ray,glm::mat4(1)),q=moving.pick(ray,glm::mat4(1));
            assert(p.has_value()==q.has_value());if(p)assert(p->identity==q->identity && p->distance==q->distance);
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(200));
        capture(moving,restored,c);assert(!moving.motionDetailReduced());assert(expected==restored && a==c);
        moving.setToolPreview({"moving"},glm::translate(transform,glm::vec3(.01F,0,0)));
        assert(moving.acceptToolCommit());capture(moving,restored,c);assert(!moving.motionDetailReduced());
        assert(moving.acceptToolUndo());capture(moving,restored,c);assert(!moving.motionDetailReduced());
        assert(glGetError()==GL_NO_ERROR);
        std::cout<<"MOTION_DETAIL endpoints/picking unchanged; full quality restored exactly after settle; commit/Undo restore full quality\n";
    }
    glfwDestroyWindow(window);glfwTerminate();return 0;
}
