namespace {
inline nadoc_vr::SidebarMenu slateKeyboard(){
    nadoc_vr::SidebarMenu m(1);m.open=true;m.placement.openDocked({0,0,0},{1,0,0,0});m.placement.setScale(1);
    m.customTab=nadoc_vr::SidebarTab{1,"text-keyboard","Text keyboard",{}};
    m.customTab->rows.push_back({"routing-help","Sample text","","",{}});
    for(auto text:{"Cancel","Create"})m.customTab->rows.push_back({std::string("routing:")+text,text,"",std::string("routing:")+text,{}});
    KeyboardGallery labels;
    for(const auto& k:nadoc_vr::textKeyboardKeys())m.customTab->rows.push_back({"routing:text-key-"+k.key,labels.label(k.key),"","routing:text-key-"+k.key,{}});
    return m;
}
inline void checkKeyboardSlate(){
    auto fixture=slateKeyboard();
    for(const auto& c:fixture.controls())if(c.id.starts_with("routing:text-key-"))for(int state=0;state<6;++state){
        auto m=fixture;auto actual=c;actual.enabled=state!=5;
        const bool hover=state==1||state==2||state==3,selected=state==4;
        const float pressure=state==2?.5F:state==3||state==5?1.F:0.F;
        m.keyboardPressure[c.id]=pressure;m.hovered=hover?c.id:"";m.isActive=[selected](const auto&){return selected;};
        const auto b=c.bounds;const float x=b.minimum.x,y=b.minimum.y,w=b.maximum.x-x,h=b.maximum.y-y;
        const auto face=!actual.enabled?glm::vec3(.16F,.19F,.23F):selected?glm::vec3(.13F,.36F,.44F):glm::vec3(.16F,.24F,.33F);
        const auto edge=hover?glm::vec3(.95F,.70F,.30F):selected?glm::vec3(.35F,.76F,1):glm::vec3(.35F,.46F,.58F);
        const float z=.026F-.006F*(actual.enabled?pressure:0.F),font=c.id.ends_with("-delete")?.0028F:.0045F;
        SolidUi original,production;original.raisedSlate(x,y,w,h,z,face,edge);
        original.text(c.label,x+(w-float(c.label.size()*6-1)*font)*.5F,y+h*.56F,font,actual.enabled?glm::vec3(.9F,.94F,1):glm::vec3(.55F,.66F,.77F),z+.004F);
        drawTextKeyboardControl(production,m,actual);
        checkGallery(original.vertices.size()==production.vertices.size(),"slate key mesh size drift");
        for(size_t i=0;i<original.vertices.size();++i)checkGallery(glm::length(original.vertices[i].position-production.vertices[i].position)<1e-6F&&glm::length(original.vertices[i].color-production.vertices[i].color)<1e-6F,"slate key differs from approved gallery");
    }
    SidebarRuntime runtime;runtime.menus[1]=fixture;auto& m=runtime.menus[1];
    auto control=[&](const std::string& id){for(auto c:m.controls())if(c.id==id)return c;throw std::runtime_error("key missing");};
    const std::string q="routing:text-key-q",w="routing:text-key-w";
    std::array<nadoc_vr::HandPose,2> hands{};
    auto aim=[&](size_t hand,const std::string& id){auto c=control(id);hands[hand]={true,false,m.placement.worldPoint({(c.bounds.minimum+c.bounds.maximum)*.5F,.4F}),{1,0,0,0}};};
    int activations=0;double now=0;
    auto input=[&](std::array<float,2> pressure,std::array<bool,2> clicks={false,false},std::array<bool,2> blocked={false,false}){
        now+=.02;runtime.input(hands,clicks,{pressure[0]>=.88F,pressure[1]>=.88F},blocked,{1e9F,1e9F},now,[&](const std::string& action,size_t){if(action.starts_with("routing:"))++activations;},pressure);
    };
    aim(0,q);aim(1,w);
    for(float p:{0.F,.25F,.5F,.75F,.85F}){input({p,1-p});checkGallery(std::abs(m.controlDepth(control(q))-(.026F-.006F*p))<1e-7F,"partial pressure depth mismatch");checkGallery(m.hit(hands[0])->id==q,"pressure changed key acquisition");}
    checkGallery(activations==0,"partial squeeze activated a key");
    aim(1,q);input({.25F,.75F});checkGallery(m.keyPressure(control(q))==.75F,"two hands did not combine pressure");
    hands[1].valid=false;input({.25F,1});checkGallery(m.keyPressure(control(q))==.25F,"tracking loss retained pressure");
    input({1,0},{true,false});input({1,0});checkGallery(activations==1,"held trigger repeated activation");
    m.available=[](const auto&){return false;};m.pressable=[](const auto&){return true;};
    input({1,0});checkGallery(m.controlDepth(control(q))==.020F,"acknowledgement wait released cap");
    m.pressable=[](const auto&){return false;};input({1,0});checkGallery(m.controlDepth(control(q))==.026F,"disabled key depressed");
    m.pressable={};m.available=[](const auto&){return true;};input({.5F,0});input({.5F,0},{false,false},{true,true});checkGallery(m.keyboardPressure.empty(),"blocked input retained pressure");
    input({.5F,0});m.open=false;input({1,0});checkGallery(m.keyboardPressure.empty(),"closed keyboard retained pressure");
    // Exercise the keyboard's actual bounds with both existing border handlers.
    m.open=true;m.placement.openDocked({0,0,-2},{1,0,0,0});m.placement.setScale(nadoc_vr::kTextKeyboardScale);
    const auto bounds=m.bounds();const auto edge=glm::vec3(bounds.maximum.x-.01F,0,0);
    nadoc_vr::RemotePanelControl remote;
    std::vector<nadoc_vr::RemotePanelTarget> targets{{&m.placement,bounds,bounds,.04F}};
    hands={};hands[1].valid=true;
    auto aimEdge=[&](glm::vec3 p){hands[1].orientation=glm::rotation(glm::vec3(0,0,-1),glm::normalize(p-hands[1].position));};
    auto remoteStep=[&](bool click,bool hold,double time){return remote.update(targets,hands,{false,click},{false,hold},{0,0,0},time);};
    aimEdge(m.placement.worldPoint(edge));checkGallery(remoteStep(true,true,1)[1],"keyboard trigger border missed");
    const auto start=m.placement.position();hands[1].position.x+=.1F;remoteStep(false,true,1.5);
    checkGallery(glm::distance(start,m.placement.position())>.09F,"keyboard trigger move failed");remoteStep(false,false,1.6);
    aimEdge(m.placement.worldPoint(edge));remoteStep(true,true,2);remoteStep(false,false,2.05);remoteStep(true,true,2.15);
    checkGallery(remote.resizing,"keyboard double trigger resize failed");
    aimEdge(m.placement.worldPoint(edge*1.2F));remoteStep(false,true,2.3);
    checkGallery(m.placement.scale()>nadoc_vr::kTextKeyboardScale*1.1F,"keyboard trigger did not resize");remoteStep(false,false,2.4);
    m.placement.openDocked({0,0,-2},{1,0,0,0});m.placement.setScale(nadoc_vr::kTextKeyboardScale);
    hands={};hands[1]={true,true,m.placement.worldPoint(edge),{1,0,0,0}};
    checkGallery(runtime.grips(hands,{false,true},[](auto,auto){})[1],"keyboard grip border missed");
    const auto gripStart=m.placement.position();hands[1].position.x+=.1F;runtime.grips(hands,{false,false},[](auto,auto){});
    checkGallery(glm::distance(gripStart,m.placement.position())>.09F,"keyboard grip move failed");
    hands[0]={true,true,m.placement.worldPoint({bounds.minimum.x+.01F,0,0}),{1,0,0,0}};
    runtime.grips(hands,{true,false},[](auto,auto){});checkGallery(m.placement.resizeActive(),"keyboard two grip resize failed");
    const auto gripScale=m.placement.scale();hands[0].position.x-=.1F;hands[1].position.x+=.1F;runtime.grips(hands,{false,false},[](auto,auto){});
    checkGallery(m.placement.scale()>gripScale,"keyboard grips did not resize");
    hands[0].pressed=hands[1].pressed=false;runtime.grips(hands,{false,false},[](auto,auto){});
    checkGallery(!m.placement.resizeActive(),"keyboard grip release failed");
    checkGallery(keyboard_slate::amount(std::numeric_limits<float>::quiet_NaN())==0&&keyboard_slate::amount(2)==1,"invalid pressure not bounded");
}
inline void captureKeyboardSlate(const std::filesystem::path& output){
    SidebarRuntime runtime;runtime.initialize();auto& m=runtime.menus[1];m=slateKeyboard();m.placement.setScale(nadoc_vr::kTextKeyboardScale);
    const std::string key="routing:text-key-d";m.hovered=key;
    for(int view=0;view<3;++view)for(int step=0;step<5;++step){
        m.keyboardPressure[key]=step*.25F;
        const auto eye=view==1?glm::vec3(.84F,.308F,1.54F):glm::vec3(0,0,1.4F);
        const auto vp=glm::perspective(glm::radians(52.F),1.28F,.01F,20.F)*glm::lookAt(eye,glm::vec3(0),glm::vec3(0,1,0));
        m.placement.openDocked(view==2?glm::vec3(10,0,0):glm::vec3(0),{1,0,0,0});
        glViewport(0,0,1280,1000);glClearColor(0,0,0,1);glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT);runtime.draw();runtime.render(vp);glFinish();
        std::vector<uint8_t> rgb(1280*1000*3);glReadPixels(0,0,1280,1000,GL_RGB,GL_UNSIGNED_BYTE,rgb.data());
        int lit=0;for(size_t i=0;i<rgb.size();i+=3)if(rgb[i]>140&&rgb[i+1]>160&&rgb[i+2]>180)++lit;
        checkGallery(view==2?lit==0:lit>2500,"production keyboard visibility/negative failed");
        const auto png=nadoc_vr::scrywrite::encodeActorEyePng(rgb,1280,1000);
        std::ofstream out(output/("slate-"+std::to_string(step*25)+(view==0?"-front.png":view==1?"-oblique.png":"-offscreen.png")),std::ios::binary);out.write(reinterpret_cast<const char*>(png.data()),png.size());
    }
    runtime.shutdown();
}

}
