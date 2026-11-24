inline void checkKeyboardGallery(const std::filesystem::path& output){
    ComponentGallery gallery;gallery.active=gallery.posed=gallery.desktop=gallery.keyboardMode=true;
    gallery.placement.openDocked({0,0,0},{1,0,0,0});gallery.placement.setScale(.75F);
    auto& k=gallery.keyboardStyles;
    k.upper=true;checkGallery(k.label("1")=="!","shifted number mismatch");k.symbols=true;
    checkGallery(k.label("r")=="$"&&k.label("dot")=="+"&&k.label("dash")=="`"&&k.label("underscore")=="~","symbol page mismatch");
    checkGallery(nadoc_vr::glyph('$')!=nadoc_vr::glyph('?')&&nadoc_vr::glyph('`')!=nadoc_vr::glyph('?'),"symbol glyph missing");
    for(int style=0;style<4;++style){
        k.reset();k.activate(style);
        const auto controls=k.controls();checkGallery(controls.size()==50,"keyboard missing controls");
        for(const auto& c:controls)if(c.id>=10){
            std::array<nadoc_vr::HandPose,2> hands{};
            hands[1]={true,false,gallery.placement.worldPoint(k.target(c.id))+glm::vec3(0,0,.3F),{1,0,0,0}};
            k.update(gallery.placement,hands,{false,true},{false,true});checkGallery(k.hover==c.id,"keyboard key ray missed");
            k.update(gallery.placement,hands,{},{ });checkGallery(k.pressed==-1,"keyboard release retained press");
        }
        k.value="test";k.activate(5);k.activate(10);checkGallery(k.value=="test","disabled keyboard typed");k.activate(5);
        k.value="Depth study";k.upper=k.symbols=false;k.hover=-1;
        for(int view=0;view<3;++view){
            const glm::vec3 eye=view==1?glm::vec3(.75F,.275F,1.375F):glm::vec3(0,0,1.25F);
            const auto vp=glm::perspective(glm::radians(52.F),1.28F,.01F,20.F)*glm::lookAt(eye,glm::vec3(0),glm::vec3(0,1,0));
            gallery.placement.openDocked(view==2?glm::vec3(10,0,0):glm::vec3(0),{1,0,0,0});
            glViewport(0,0,1280,1000);glClearColor(0,0,0,1);glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT);gallery.render(vp);glFinish();
            std::vector<uint8_t> rgb(1280*1000*3);glReadPixels(0,0,1280,1000,GL_RGB,GL_UNSIGNED_BYTE,rgb.data());
            int lit=0;for(size_t p=0;p<rgb.size();p+=3)if(rgb[p]>140&&rgb[p+1]>160&&rgb[p+2]>180)++lit;
            checkGallery(view==2?lit==0:lit>3000,"keyboard visible pixels/offscreen negative failed");
            const auto png=nadoc_vr::scrywrite::encodeActorEyePng(rgb,1280,1000);
            std::ofstream out(output/("keyboard-"+std::to_string(style+1)+(view==0?"-front.png":view==1?"-oblique.png":"-offscreen.png")),std::ios::binary);out.write(reinterpret_cast<const char*>(png.data()),png.size());
        }
        gallery.placement.openDocked({0,0,0},{1,0,0,0});
    }
    gallery.ui.shutdown();
}
