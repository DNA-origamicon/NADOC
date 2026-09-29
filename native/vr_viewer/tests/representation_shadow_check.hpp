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
        scene.renderShadowMap(glm::mat4(1),{.6F,0,1});
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
