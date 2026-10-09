#pragma once
#include "component_gallery.hpp"

inline int runComponentGalleryDesktop(const std::string& output,bool buttons=false,bool cards=false,bool lists=false) {
    if(!glfwInit())throw std::runtime_error("Could not initialize the desktop display");
    glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR,3);glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR,3);
    glfwWindowHint(GLFW_OPENGL_PROFILE,GLFW_OPENGL_CORE_PROFILE);glfwWindowHint(GLFW_SAMPLES,4);
    GLFWwindow* window=glfwCreateWindow(1280,1050,"NADOC VR Component Gallery - Thumbwheel | Drag: value | Right drag: orbit | Scroll: zoom | F: front | O: angled | Space: demo | R: reset | S: capture | Esc: close",nullptr,nullptr);
    if(!window){glfwTerminate();throw std::runtime_error("Could not create the component gallery window");}
    glfwMakeContextCurrent(window);glfwSwapInterval(1);
    if(buttons)glfwSetWindowTitle(window,"NADOC VR Component Gallery - Buttons | Click: select | F: front | O: angled | Space: demo | R: reset | S: capture | Esc: close");
    if(cards)glfwSetWindowTitle(window,"NADOC VR Component Gallery - Cards and lists | Click: expand/select | F: front | O: angled | Space: demo | R: reset | Esc: close");
    if(lists)glfwSetWindowTitle(window,"NADOC VR Component Gallery - Scrollable sets | Click: row/action | Drag rail: scroll | F: front | O: angled | Space: demo | R: reset | Esc: close");
    ComponentGallery gallery;gallery.listMode=lists;gallery.cardMode=cards;gallery.buttonMode=buttons;gallery.active=true;gallery.posed=true;gallery.desktop=true;
    gallery.placement.openDocked({0,0,0},{1,0,0,0});
    struct View {float yaw=.30F,pitch=.14F,distance=1.25F;};
    View view;glfwSetWindowUserPointer(window,&view);
    glfwSetScrollCallback(window,[](GLFWwindow* w,double,double y){auto& v=*static_cast<View*>(glfwGetWindowUserPointer(w));v.distance=std::clamp(v.distance-float(y)*.08F,.65F,2.5F);});
    std::array<bool,GLFW_KEY_LAST+1> previousKeys{};
    bool previousPressed=false,previousOrbit=false;double oldX=0,oldY=0,last=glfwGetTime();
    bool first=true;int capture=0;
    while(!gStopRequested && !glfwWindowShouldClose(window)) {
        glfwPollEvents();
        auto key=[&](int k){bool down=glfwGetKey(window,k)==GLFW_PRESS;bool clicked=down&&!previousKeys[k];previousKeys[k]=down;return clicked;};
        if(key(GLFW_KEY_ESCAPE))glfwSetWindowShouldClose(window,true);
        if(key(GLFW_KEY_F)){view.yaw=view.pitch=0;view.distance=1.25F;}
        if(key(GLFW_KEY_O)){view.yaw=.48F;view.pitch=.20F;view.distance=1.25F;}
        if(key(GLFW_KEY_SPACE))gallery.toggleDemo();
        if(key(GLFW_KEY_R)){gallery.reset();gallery.demo=false;}
        const bool save=key(GLFW_KEY_S)||first;
        double x,y;glfwGetCursorPos(window,&x,&y);
        const bool orbit=glfwGetMouseButton(window,GLFW_MOUSE_BUTTON_RIGHT)==GLFW_PRESS;
        if(orbit && previousOrbit){view.yaw=std::clamp(view.yaw+float(x-oldX)*.005F,-1.F,1.F);view.pitch=std::clamp(view.pitch+float(y-oldY)*.005F,-.7F,.7F);}
        oldX=x;oldY=y;previousOrbit=orbit;
        int width,height,windowWidth,windowHeight;
        glfwGetFramebufferSize(window,&width,&height);glfwGetWindowSize(window,&windowWidth,&windowHeight);
        if(width<=0||height<=0){glfwWaitEventsTimeout(.05);continue;}
        const auto rotation=glm::quat(glm::vec3(-view.pitch,view.yaw,0));
        const glm::vec3 eye=rotation*glm::vec3(0,0,view.distance);
        const auto vp=glm::perspective(glm::radians(52.F),float(width)/height,.01F,10.F)*glm::lookAt(eye,glm::vec3(0),glm::vec3(0,1,0));
        const glm::vec2 ndc(float(x)/std::max(1,windowWidth)*2-1,1-float(y)/std::max(1,windowHeight)*2);
        auto far=glm::inverse(vp)*glm::vec4(ndc,1,1);far/=far.w;
        std::array<nadoc_vr::HandPose,2> hands{};
        hands[1]={true,false,eye,glm::rotation(glm::vec3(0,0,-1),glm::normalize(glm::vec3(far)-eye))};
        const bool pressed=glfwGetWindowAttrib(window,GLFW_FOCUSED) && glfwGetMouseButton(window,GLFW_MOUSE_BUTTON_LEFT)==GLFW_PRESS;
        const double now=glfwGetTime();
        gallery.update(hands,{false,pressed&&!previousPressed},{false,pressed},float(now-last),eye,rotation);
        // Recenter in desktop mode restores the panel, without changing its scale.
        gallery.placement.openDocked({0,0,0},{1,0,0,0});
        last=now;previousPressed=pressed;
        glViewport(0,0,width,height);glClearColor(.018F,.025F,.038F,1);glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT);
        gallery.render(vp);
        if(save && !output.empty()) {
            std::filesystem::create_directories(output);
            const auto base=std::filesystem::path(output)/("desktop-"+std::to_string(capture++));
            std::vector<uint8_t> rgb(size_t(width)*height*3);
            glPixelStorei(GL_PACK_ALIGNMENT,1);glReadPixels(0,0,width,height,GL_RGB,GL_UNSIGNED_BYTE,rgb.data());
            const auto png=nadoc_vr::scrywrite::encodeActorEyePng(rgb,width,height);
            std::ofstream image(base.string()+".png",std::ios::binary);image.write(reinterpret_cast<const char*>(png.data()),png.size());
            std::ofstream state(base.string()+".json");state<<gallery.observation();
        }
        first=false;glfwSwapBuffers(window);
    }
    gallery.ui.shutdown();glfwDestroyWindow(window);glfwTerminate();return 0;
}
