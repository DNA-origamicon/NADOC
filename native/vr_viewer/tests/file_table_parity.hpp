// Frozen option-4 reference checks production geometry and every coloured vertex.
inline nadoc_vr::SidebarMenu fileParityMenu(){
    nadoc_vr::SidebarMenu menu(1);menu.open=true;
    menu.customTab=nadoc_vr::SidebarTab{1,"file-browser","File",{}};
    const std::array<std::string,5> ids{"new","assembly","open","save","close"};
    const std::array<std::string,5> labels{"NEW PART","NEW ASSEMBLY","OPEN","SAVE AS","CLOSE SESSION"};
    for(size_t i=0;i<5;++i)menu.customTab->rows.push_back({"routing:file-"+ids[i],labels[i],"","routing:file-"+ids[i],{}});
    menu.customTab->rows.push_back({"routing-help","WORKSPACE / DESIGNS >","","",{}});
    for(size_t i=0;i<6;++i)menu.customTab->rows.push_back({"routing:file-entry-"+std::to_string(i),FileGallery::files[i],"PART|TODAY|24 KB","routing:file-entry-"+std::to_string(i),{}});
    menu.available=[](const auto& action){return action!="routing:file-assembly";};
    return menu;
}
inline void checkFileTableParity(){
    auto menu=fileParityMenu();const auto controls=menu.controls();
    for(size_t i=0;i<controls.size();++i){
        const auto& c=controls[i];const bool entry=i>=6;
        const float x=i<5?-.73F:-.33F,y=i<5?.265F-float(i)*.125F:i==5?.305F:.15F-float(i-6)*.083F;
        const float w=i<5?.32F:.97F,h=i<5?.095F:i==5?.065F:.072F;
        checkGallery(glm::length(c.bounds.minimum-glm::vec2(x,y))<1e-6F&&glm::length(c.bounds.maximum-glm::vec2(x+w,y+h))<1e-6F,"File control differs from option 4 geometry");
        for(int state=0;state<4;++state){
            auto actual=c;actual.active=state==2;actual.enabled=state!=3;const bool focus=state==1;
            const bool enabled=actual.enabled||c.id=="routing-help",chosen=actual.active;
            SolidUi original,production;
            const auto tint=!enabled?glm::vec3(.24F,.29F,.34F):chosen?glm::vec3(.15F,.38F,.48F):glm::vec3(.12F,.20F,.28F);
            const auto edge=focus?glm::vec3(.95F,.70F,.30F):chosen?glm::vec3(.35F,.76F,1):glm::vec3(.30F,.43F,.55F);
            original.rounded(x,y,w,h,.009F,edge,.012F);
            original.rounded(x+.003F,y+.003F,w-.006F,h-.006F,.007F,tint,.014F);
            original.text(c.label,x+.015F,y+h*.60F,entry?.0031F:.0034F,enabled?glm::vec3(.9F,.94F,1):glm::vec3(.55F,.66F,.77F),.030F);
            if(entry)original.text("PART   TODAY   24 KB",x+.41F,y+.043F,.0028F,{.55F,.66F,.77F},.030F);
            drawFileTableControl(production,actual,focus);
            checkGallery(original.vertices.size()==production.vertices.size(),"File control mesh differs from option 4");
            for(size_t v=0;v<original.vertices.size();++v){
                checkGallery(glm::length(original.vertices[v].position-production.vertices[v].position)<1e-6F,"File control depth/spacing/font differs from option 4");
                checkGallery(glm::length(original.vertices[v].color-production.vertices[v].color)<1e-6F,"File control colour differs from option 4");
            }
        }
    }
}
inline void captureFileTableParity(const std::filesystem::path& output){
    SidebarRuntime runtime;runtime.initialize();runtime.menus[1]=fileParityMenu();
    ComponentGallery reference;reference.active=reference.posed=reference.fileMode=true;reference.fileStyles.choose(3);
    for(int view=0;view<3;++view){
        const glm::vec3 eye=view==1?glm::vec3(.6F,.22F,1.1F):glm::vec3(0,0,1.25F);
        const auto vp=glm::perspective(glm::radians(52.F),1.28F,.01F,20.F)*glm::lookAt(eye,glm::vec3(0),glm::vec3(0,1,0));
        const glm::vec3 position=view==2?glm::vec3(10,0,0):glm::vec3(0);
        runtime.menus[1].placement.openDocked(position,{1,0,0,0});runtime.menus[1].placement.setScale(.9F);
        reference.placement=runtime.menus[1].placement;
        for(int which=0;which<2;++which){
            glViewport(0,0,1280,1000);glClearColor(0,0,0,1);glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT);
            if(which==0){runtime.draw();runtime.render(vp);}else reference.render(vp);
            glFinish();std::vector<uint8_t> rgb(1280*1000*3);glReadPixels(0,0,1280,1000,GL_RGB,GL_UNSIGNED_BYTE,rgb.data());
            int lit=0;for(size_t i=0;i<rgb.size();i+=3)if(rgb[i]>60&&rgb[i+1]>80&&rgb[i+2]>100)++lit;
            checkGallery(view==2?lit==0:lit>18000,"File parity rendering missing/negative failed");
            const auto png=nadoc_vr::scrywrite::encodeActorEyePng(rgb,1280,1000);
            std::ofstream out(output/(std::string(which==0?"production-":"reference-")+(view==0?"front.png":view==1?"oblique.png":"offscreen.png")),std::ios::binary);
            out.write(reinterpret_cast<const char*>(png.data()),png.size());
        }
    }
    runtime.shutdown();reference.ui.shutdown();
}
