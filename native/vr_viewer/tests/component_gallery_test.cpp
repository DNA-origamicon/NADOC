#define main nadocViewerMain
#include "../src/main.cpp"
#undef main

void checkGallery(bool condition,const char* message) {if(!condition)throw std::runtime_error(message);}
int main(int argc,char** argv) {
    ComponentGallery gallery;gallery.active=gallery.posed=true;
    gallery.placement.openDocked({0,0,0},glm::quat(glm::vec3(.12F,.42F,0)));
    std::array<nadoc_vr::HandPose,2> hands{};
    const auto normal=gallery.placement.orientation()*glm::vec3(0,0,1);
    const auto up=gallery.placement.orientation()*glm::vec3(0,1,0);
    for(size_t i=0;i<9;++i) {
        gallery.reset();
        const auto target=gallery.placement.worldPoint(ComponentGallery::center(i));
        hands[1]={true,false,target+normal*.3F,gallery.placement.orientation()};
        gallery.update(hands,{false,false},{false,false},.01F,{},{});
        checkGallery(gallery.wheels[i].hovered,"raised wheel ray not acquired");
        gallery.update(hands,{false,true},{false,true},.01F,{},{});
        checkGallery(gallery.wheels[i].control.dragging(),"trigger failed to grab wheel");
        const int before=gallery.wheels[i].value;
        for(int frame=0;frame<12;++frame) {
            hands[1].position+=up*.004F;
            gallery.update(hands,{false,false},{false,true},.01F,{},{});
        }
        checkGallery(gallery.wheels[i].value>before,"drag failed to change value");
        gallery.update(hands,{false,false},{false,false},.01F,{},{});
        checkGallery(!gallery.wheels[i].control.dragging(),"release retained ownership");
        checkGallery(gallery.wheels[i].control.moving(),"flick lost inertia");
        for(int frame=0;frame<600;++frame)gallery.update(hands,{false,false},{false,false},.01F,{},{});
        checkGallery(!gallery.wheels[i].control.moving(),"inertia failed to settle");
        checkGallery(gallery.wheels[i].value<=gallery.wheels[i].maximum,"coasting escaped range");
        hands[1].valid=false;
    }
    gallery.reset();gallery.demo=true;
    for(int frame=0;frame<3200;++frame)gallery.update(hands,{false,false},{false,false},.01F,{},{});
    for(const auto& wheel:gallery.wheels)checkGallery(wheel.value>=0&&wheel.value<=wheel.maximum,"tour exceeded range");
    gallery.buttonMode=true;gallery.reset();
    for(size_t i=0;i<6;++i) {
        const size_t hand=i%2;hands={};
        auto target=ButtonGallery::center(i);target.z=gallery.buttonStyles.frontDepth(i);
        hands[hand]={true,false,gallery.placement.worldPoint(target)+normal*.3F,gallery.placement.orientation()};
        std::array<bool,2> held{};held[hand]=true;
        gallery.update(hands,{},{},.01F,{},{});
        checkGallery(gallery.buttonStyles.buttons[i].hovered,"button ray missed");
        gallery.update(hands,held,held,.01F,{},{});
        checkGallery(gallery.buttonStyles.buttons[i].clicks==0,"button activated before release");
        for(int f=0;f<12;++f)gallery.update(hands,{},held,.01F,{},{});
        checkGallery(gallery.buttonStyles.buttons[i].press>.8F,"button lacks travel");
        gallery.update(hands,{},{},.01F,{},{});
        checkGallery(gallery.buttonStyles.buttons[i].selected && gallery.buttonStyles.buttons[i].clicks==1,"button did not activate on release");
        gallery.buttonStyles.disabled=true;
        gallery.update(hands,held,held,.01F,{},{});gallery.update(hands,{},{},.01F,{},{});
        checkGallery(gallery.buttonStyles.buttons[i].clicks==1,"disabled button activated");
        gallery.buttonStyles.disabled=false;
        gallery.update(hands,held,held,.01F,{},{});hands[hand].position+=up*.3F;
        gallery.update(hands,{},held,.01F,{},{});gallery.update(hands,{},{},.01F,{},{});
        checkGallery(gallery.buttonStyles.buttons[i].clicks==1,"release outside button activated");
    }
    gallery.buttonMode=false;gallery.cardMode=true;gallery.reset();
    for(size_t i=0;i<6;++i){
        hands={};const auto aim=[&](int row){hands[1]={true,false,gallery.placement.worldPoint(CardGallery::target(i,row))+normal*.3F,gallery.placement.orientation()};};
        const auto frame=[&](bool click,bool held){gallery.update(hands,{false,click},{false,held},.02F,{},{});};
        aim(0);frame(false,false);checkGallery(gallery.cardStyles.cards[i].hover==0,"card header not acquired");
        frame(true,true);checkGallery(!gallery.cardStyles.cards[i].open,"card opened before release");frame(false,false);
        checkGallery(gallery.cardStyles.cards[i].open,"card did not expand");
        for(int n=0;n<25;++n)frame(false,false);
        aim(1);frame(true,true);frame(false,false);checkGallery(gallery.cardStyles.cards[i].selected==1,"child not selected");
        aim(2);frame(true,true);frame(false,false);checkGallery(gallery.cardStyles.cards[i].selected==2,"row selection not exclusive");
        gallery.cardStyles.disabled=true;aim(0);frame(true,true);frame(false,false);checkGallery(gallery.cardStyles.cards[i].open,"disabled card changed");
        gallery.cardStyles.disabled=false;frame(true,true);hands[1].position+=up*.3F;frame(false,false);checkGallery(gallery.cardStyles.cards[i].open,"outside release expanded card");
        aim(0);frame(true,true);frame(false,false);checkGallery(!gallery.cardStyles.cards[i].open,"card did not collapse");
        aim(1);frame(false,false);checkGallery(gallery.cardStyles.cards[i].hover==-1,"collapsed child accepts input");
    }
    gallery.cardMode=false;gallery.buttonMode=false;gallery.listMode=true;gallery.reset();
    for(size_t i=0;i<6;++i){
        auto& sample=gallery.listStyles.samples[i];hands={};
        const auto aim=[&](int control){hands[1]={true,false,gallery.placement.worldPoint(ListGallery::target(i,control))+normal*.3F,gallery.placement.orientation()};};
        const auto frame=[&](bool click,bool held){gallery.update(hands,{false,click},{false,held},.02F,{},{});};
        const auto click=[&](int control){aim(control);frame(true,true);frame(false,false);};
        aim(0);frame(true,true);checkGallery(sample.list.selected==-1,"list selected on press");frame(false,false);
        checkGallery(sample.list.selected==0,"list selection missed");
        const int value=sample.list.items[0].value;click(2);
        checkGallery(i==1||i==3?sample.list.items[0].value==value+1:sample.list.items[0].pinned,"row action missed");
        checkGallery(sample.list.selected==0,"row action changed selection");
        for(int j=0;j<15;++j)click(10);
        checkGallery(sample.list.offset==9 && sample.list.selected==0,"list overflow or lost selection");
        click(6);checkGallery(sample.list.selected==11,"last item unreachable");
        for(int j=0;j<15;++j)click(9);
        checkGallery(sample.list.offset==0,"list underflow");
        checkGallery(i==1||i==3?sample.list.items[0].value==value+1:sample.list.items[0].pinned,"row action lost after scroll");
        aim(0);frame(true,true);hands[1].position+=up*.3F;frame(false,false);
        checkGallery(sample.list.selected==11,"outside release activated row");
        aim(0);frame(true,true);hands[1].valid=false;frame(false,false);hands[1].valid=true;frame(false,false);
        checkGallery(sample.list.selected==11,"tracking loss activated row");
        aim(11);frame(true,true);hands[1].position-=up*.5F;frame(false,true);frame(false,false);
        checkGallery(sample.list.offset==9,"drag rail cannot reach end");
        gallery.listStyles.disabled=true;const int clicks=sample.clicks;click(9);click(0);
        checkGallery(sample.clicks==clicks && sample.list.offset==9,"disabled list accepts input");
        gallery.listStyles.disabled=false;
        const auto c=ListGallery::center(i);checkGallery(gallery.listStyles.hit(i,c+glm::vec3(-.1F,-.145F,0))==-1,"offscreen row has hit target");
    }
    // The model also handles empty and shorter-than-viewport sets.
    nadoc_vr::ScrollableSet empty;empty.scroll(100);empty.seek(1);
    checkGallery(empty.offset==0 && empty.index(0)==-1,"empty list bounds");
    empty.items.push_back({"one","",1});empty.scroll(100);
    checkGallery(empty.offset==0 && empty.index(0)==0 && empty.index(1)==-1,"short list bounds");
    gallery.listMode=false;
    gallery.cardMode=false;
    gallery.buttonMode=false;
    // Render exact native meshes and retain front/oblique plus offscreen negative.
    if(!glfwInit())return 77;
    glfwWindowHint(GLFW_VISIBLE,GLFW_FALSE);glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR,3);glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR,3);
    auto* window=glfwCreateWindow(1280,1000,"Gallery validation",nullptr,nullptr);
    if(!window){glfwTerminate();return 77;}
    glfwMakeContextCurrent(window);
    gallery.reset();gallery.demo=false;gallery.placement.openDocked({0,0,0},{1,0,0,0});
    const std::filesystem::path output=argc>1?argv[1]:"gallery-evidence";
    std::filesystem::create_directories(output);
    for(int mode=0;mode<4;++mode)for(int view=0;view<3;++view) {
        gallery.buttonMode=mode==1;gallery.cardMode=mode==2;gallery.listMode=mode==3;
        if(mode==2)for(auto& card:gallery.cardStyles.cards){card.open=true;card.reveal=1;}gallery.placement.openDocked({0,0,0},{1,0,0,0});
        const glm::vec3 eye=view==1?glm::vec3(.6F,.22F,1.1F):glm::vec3(0,0,1.25F);
        const auto vp=glm::perspective(glm::radians(52.F),1.28F,.01F,20.F)*glm::lookAt(eye,glm::vec3(0),glm::vec3(0,1,0));
        if(view==2)gallery.placement.openDocked({10,0,0},{1,0,0,0});
        glViewport(0,0,1280,1000);glClearColor(0,0,0,1);glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT);
        gallery.render(vp);glFinish();
        std::vector<uint8_t> rgb(1280*1000*3);glReadPixels(0,0,1280,1000,GL_RGB,GL_UNSIGNED_BYTE,rgb.data());
        int bright=0;for(size_t p=0;p<rgb.size();p+=3)if(rgb[p]>60 && rgb[p+1]>80 && rgb[p+2]>100)++bright;
        checkGallery(view==2?bright==0:bright>18000,"gallery pixel coverage/negative control failed");
        auto png=nadoc_vr::scrywrite::encodeActorEyePng(rgb,1280,1000);
        std::ofstream file(output/(std::string(mode==3?"lists-":mode==2?"cards-":mode==1?"buttons-":"")+(view==0?"front.png":view==1?"oblique.png":"offscreen.png")),std::ios::binary);
        file.write(reinterpret_cast<const char*>(png.data()),png.size());
    }
    gallery.ui.shutdown();glfwDestroyWindow(window);glfwTerminate();
    std::cout<<"Wheel, button, card and six scrollable set interactions and rendered pixels passed\n";
}
