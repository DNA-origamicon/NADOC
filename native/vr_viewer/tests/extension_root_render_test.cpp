// Render unchanged saved models before/after a display-only connector fix.
#define main nadoc_viewer_entry_point
#include "../src/main.cpp"
#undef main
#include <cassert>
int main(int argc,char** argv){
    if(argc!=4)return 2;
    if(!glfwInit())return 77;
    glfwWindowHint(GLFW_VISIBLE,GLFW_FALSE);
    glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR,4);glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR,3);
    auto* window=glfwCreateWindow(900,900,"Extension root rendering",nullptr,nullptr);
    if(!window)return 77;
    glfwMakeContextCurrent(window);glEnable(GL_DEPTH_TEST);
    {
        auto before=loadScene(argv[1]),after=loadScene(argv[2]);
        const std::filesystem::path output(argv[3]);std::filesystem::create_directories(output);
        const auto ri=representationSourceIndex(Representation::full);
        std::unordered_set<std::string> oldIds;
        for(const auto& c:before.representations[ri].cylinders)oldIds.insert(c.identity);
        std::vector<StyledCylinder> added;
        for(const auto& c:after.representations[ri].cylinders)if(!oldIds.contains(c.identity) && c.identity.find("__ext_")!=std::string::npos && c.identity.find("__ext_")==c.identity.rfind("__ext_"))added.push_back(c);
        assert(!added.empty());
        GlScene oldScene(before,true,{}, {},false),newScene(after,true,{}, {},false);
        auto capture=[&](GlScene& scene,const glm::mat4& vp,const std::string& name){
            scene.setStyle(Representation::full,Coloring::strand);
            glViewport(0,0,900,900);glClearColor(.015F,.02F,.03F,1);glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT);
            scene.render(vp,glm::mat4(1),{},false);glFinish();
            std::vector<uint8_t> rgb(900*900*3);glReadPixels(0,0,900,900,GL_RGB,GL_UNSIGNED_BYTE,rgb.data());
            auto png=nadoc_vr::scrywrite::encodeActorEyePng(rgb,900,900);
            std::ofstream file(output/(name+".png"),std::ios::binary);file.write(reinterpret_cast<const char*>(png.data()),png.size());
            assert(glGetError()==GL_NO_ERROR);return rgb;
        };
        for(size_t i=0;i<added.size();++i){
            const auto& bond=added[i];const auto center=(bond.start+bond.end)*.5F;
            const auto axis=glm::normalize(bond.end-bond.start);
            auto up=std::abs(axis.y)<.9F?glm::vec3(0,1,0):glm::vec3(1,0,0);
            const auto normal=glm::normalize(glm::cross(axis,up));
            size_t changed=0;
            for(int view=0;view<2;++view){
                const auto eye=center+(view==0?normal:glm::normalize(normal+up))*after.normalizationScale*3.F;
                const auto vp=glm::perspective(glm::radians(52.F),1.F,.0001F,100.F)*glm::lookAt(eye,center,up);
                const auto name="root-"+std::to_string(i)+"-view-"+std::to_string(view);
                const auto a=capture(oldScene,vp,name+"-before"),b=capture(newScene,vp,name+"-after");
                for(size_t j=0;j<a.size();++j)changed+=a[j]!=b[j];
            }
            assert(changed>100);std::cout<<bond.identity<<" changed_bytes="<<changed<<'\n';
        }
    }
    glfwDestroyWindow(window);glfwTerminate();
}
