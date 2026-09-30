#define main nadoc_viewer_entry_point
#include "../src/main.cpp"
#undef main
#include <cassert>
int main(int argc,char** argv){
    if(argc!=2)return 2;
    if(!glfwInit())return 77;
    glfwWindowHint(GLFW_VISIBLE,GLFW_FALSE);glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR,4);glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR,3);
    auto* window=glfwCreateWindow(1024,1024,"resident render comparison",nullptr,nullptr);if(!window)return 77;
    glfwMakeContextCurrent(window);glEnable(GL_DEPTH_TEST);
    {
        auto data=loadScene(argv[1]);data.initialRepresentation=Representation::stick;
        GlScene scene(std::move(data),false,{}, {},false);
        const auto vp=glm::perspective(glm::radians(90.F),1.F,.05F,100.F);
        GLuint query;glGenQueries(1,&query);
        std::vector<unsigned char> reference(1024*1024*4),actual(reference.size());
        for(bool staged:{false,true}){
            if(staged){scene.enablePreparedStyles();scene.setStyle(Representation::stick,Coloring::strand);while(scene.stylePending())scene.pollPreparedStyle();}
            std::vector<double> gpu,cpu;
            for(int i=0;i<110;++i){
                auto start=std::chrono::steady_clock::now();
                glBeginQuery(GL_TIME_ELAPSED,query);
                const auto model=glm::rotate(glm::mat4(1),float(i)*.002F,glm::vec3(0,1,0));
                scene.renderShadowMap(model,glm::normalize(glm::vec3(.577F,.577F,.577F)));
                glBindFramebuffer(GL_FRAMEBUFFER,0);glViewport(0,0,1024,1024);glDrawBuffer(GL_BACK);
                for(int eye=0;eye<2;++eye){glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT);scene.render(vp,model,{},false);}
                glEndQuery(GL_TIME_ELAPSED);auto finish=std::chrono::steady_clock::now();
                GLuint64 ns;glGetQueryObjectui64v(query,GL_QUERY_RESULT,&ns);
                if(i>=10){gpu.push_back(double(ns)/1e6);cpu.push_back(std::chrono::duration<double,std::milli>(finish-start).count());}
            }
            glReadPixels(0,0,1024,1024,GL_RGBA,GL_UNSIGNED_BYTE,(staged?actual:reference).data());
            std::sort(gpu.begin(),gpu.end());std::sort(cpu.begin(),cpu.end());
            std::cout<<"RESIDENT_RENDER staged="<<staged<<" gpu_p50_ms="<<gpu[50]<<" gpu_p95_ms="<<gpu[95]<<" cpu_p95_ms="<<cpu[95]<<std::endl;
        }
        size_t differences=0;for(size_t i=0;i<actual.size();++i)differences+=actual[i]!=reference[i];
        std::cout<<"RESIDENT_RENDER differing_color_bytes="<<differences<<std::endl;
        assert(differences==0);glDeleteQueries(1,&query);assert(glGetError()==GL_NO_ERROR);
    }
    glfwDestroyWindow(window);glfwTerminate();
}
