// Real GL pixels, identical geometry across styles, plus a removed-occluder control.
void verifyRepresentationShadows(GLuint framebuffer) {
    SceneData data;data.available.fill(true);
    ColorSet colors;colors.values.fill({.8F,.6F,.4F});
    for(auto& rep:data.representations) {
        rep.cylinders.push_back({"receiver",{-.8F,0,-2},{.8F,0,-2},.18F,colors});
        rep.cylinders.push_back({"occluder",{.3F,-.5F,-1.5F},{.3F,.5F,-1.5F},.12F,colors});
    }
    auto render=[&](GlScene& scene,Representation rep) {
        scene.setStyle(rep,Coloring::strand);
        glEnable(GL_DEPTH_TEST);glDepthFunc(GL_LESS);
        const nadoc_vr::ShadowLightFrame light{{.6F,0,1},{0,1,0}};
        scene.renderShadowMap(glm::mat4(1),light,&light);
        glBindFramebuffer(GL_FRAMEBUFFER,framebuffer);glViewport(0,0,128,128);
        glDrawBuffer(GL_COLOR_ATTACHMENT0);glClearColor(0,0,0,0);
        glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT);
        scene.render(glm::perspective(glm::radians(90.F),1.F,.05F,10.F),glm::mat4(1),{},false);
        std::vector<unsigned char> pixels(128*128*4);
        glReadBuffer(GL_COLOR_ATTACHMENT0);glReadPixels(0,0,128,128,GL_RGBA,GL_UNSIGNED_BYTE,pixels.data());
        requireLive(glGetError()==GL_NO_ERROR,"shadow fixture GL error");
        return pixels;
    };
    GlScene scene(data);
    const auto reference=render(scene,Representation::full);
    for(size_t i=0;i<kRepresentationCount;++i)
        if(static_cast<Representation>(i)!=Representation::vdw) // VDW intentionally suppresses bonds.
        requireLive(render(scene,static_cast<Representation>(i))==reference,"Representation lighting differs for identical bonds");
    for(auto& rep:data.representations)rep.cylinders.pop_back();
    GlScene unoccluded(data);
    const auto control=render(unoccluded,Representation::full);
    size_t shadowPixels=0;
    // Left of the visible occluder: only its cast shadow can darken the receiver.
    for(int y=58;y<70;++y)for(int x=45;x<65;++x) {
        const auto index=4*(y*128+x);
        if(reference[index]>10 && control[index]>reference[index]+20)++shadowPixels;
    }
    requireLive(shadowPixels>15,"Removed occluder did not remove a visible cast shadow");
    std::cout<<"All representation bond lighting matches; "<<shadowPixels<<" cast-shadow pixels verified\n";
}

// An off-axis frustum shifts this billboard on screen but must not rotate its
// world-space normals or change its lighting. Exercise the production shaders.
void verifySphereProjectionLighting(GLuint framebuffer) {
    SceneData data;data.available.fill(true);
    ColorSet colors;colors.values.fill({.8F,.6F,.4F});
    data.representations[static_cast<size_t>(Representation::full)].points =
        {{"sphere",{0,0,-2},colors,.65F}};
    GlScene scene(data);
    auto render=[&](float skewX,float skewY,glm::vec3 direction) {
        glEnable(GL_DEPTH_TEST);glDepthFunc(GL_LESS);
        scene.renderShadowMap(glm::mat4(1),{direction,{0,1,0}});
        glBindFramebuffer(GL_FRAMEBUFFER,framebuffer);glViewport(0,0,128,128);
        glDrawBuffer(GL_COLOR_ATTACHMENT0);glClearColor(0,0,0,0);
        glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT);
        auto projection=glm::perspective(glm::radians(90.F),1.F,.05F,10.F);
        projection[2][0]=skewX;projection[2][1]=skewY;
        scene.render(projection,glm::mat4(1),{},false);
        std::vector<unsigned char> pixels(128*128*4);
        glReadBuffer(GL_COLOR_ATTACHMENT0);
        glReadPixels(0,0,128,128,GL_RGBA,GL_UNSIGNED_BYTE,pixels.data());
        requireLive(glGetError()==GL_NO_ERROR,"Sphere projection fixture GL error");
        return pixels;
    };
    const glm::vec3 light(-1,1,1);
    const auto reference=render(0,0,light);
    size_t visible=0;
    for(int y=40;y<88;++y)for(int x=40;x<88;++x)
        visible+=reference[4*(y*128+x)]>20;
    requireLive(visible>200,"Sphere projection fixture is blank or too small");
    for(int sign:{-1,1}) {
        const auto shifted=render(sign*.25F,sign*.125F,light);
        int worst=0;
        for(int y=40;y<88;++y)for(int x=40;x<88;++x)for(int c=0;c<3;++c)
            worst=std::max(worst,std::abs(int(reference[4*(y*128+x)+c])-
                int(shifted[4*((y-sign*8)*128+x-sign*16)+c])));
        requireLive(worst<=1,"Asymmetric projection changed sphere shading");
    }
    const auto changed=render(0,0,{-1,-1,-1});
    size_t changedPixels=0;
    for(size_t i=0;i<reference.size();i+=4)
        changedPixels+=std::abs(int(reference[i])-int(changed[i]))>20;
    requireLive(changedPixels>100,"Sphere lighting negative control did not change pixels");
    std::cout<<"Sphere lighting invariant under both off-axis frusta; negative control verified\n";
}
