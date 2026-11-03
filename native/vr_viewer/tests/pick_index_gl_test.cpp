#define main nadoc_viewer_entry_point
#include "../src/main.cpp"
#undef main
#include <cassert>
#include <random>
int main(int argc,char** argv){
    if(argc!=2)return 2;
    assert(glfwInit());glfwWindowHint(GLFW_VISIBLE,GLFW_FALSE);
    glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR,4);glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR,3);
    auto* window=glfwCreateWindow(128,128,"pick parity",nullptr,nullptr);assert(window);glfwMakeContextCurrent(window);
    {
        std::mt19937 rng(7192);std::uniform_real_distribution<float> dist(-.7F,.7F);
        for(auto rep:{Representation::stick,Representation::ballstick}){
            auto data=loadScene(argv[1]);
            std::vector<glm::vec3> targets;
            for(const auto& point:data.representations[representationSourceIndex(rep)].points)targets.push_back(point.position);
            for(const auto& cylinder:data.representations[representationSourceIndex(rep)].cylinders)targets.push_back((cylinder.start+cylinder.end)*.5F);
            assert(!targets.empty());
            GlScene scene(std::move(data),false,{}, {},false);
            scene.setStyle(rep,Coloring::strand);
            std::vector<std::pair<nadoc_vr::Ray,glm::mat4>> queries;
            for(int i=0;i<180;++i){
                auto model=glm::translate(glm::mat4(1),glm::vec3(.03F,-.02F,.07F));
                model=glm::rotate(model,float(i%3)*.25F,glm::vec3(0,1,0));
                model=glm::scale(model,glm::vec3(1.F+float(i%3)*.2F));
                glm::vec3 origin(0),target(dist(rng),dist(rng),-1.6F);
                if(i%3)target=glm::vec3(model*glm::vec4(targets[(size_t(i)*997)%targets.size()],1));
                queries.push_back({{origin,glm::normalize(target-origin)},model});
            }
            std::vector<std::optional<nadoc_vr::PickHit>> expected;
            auto before=std::chrono::steady_clock::now();
            for(const auto& [ray,model]:queries)expected.push_back(scene.pick(ray,model));
            const double legacy=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-before).count();
            scene.enablePreparedStyles();scene.setStyle(rep,Coloring::strand);
            while(scene.stylePending())scene.pollPreparedStyle();
            size_t hits=0;before=std::chrono::steady_clock::now();
            for(size_t i=0;i<queries.size();++i){
                const auto actual=scene.pick(queries[i].first,queries[i].second);assert(bool(actual)==bool(expected[i]));
                if(actual){++hits;if(actual->identity!=expected[i]->identity)std::cerr<<"PICK_MISMATCH ray="<<i<<" actual="<<actual->identity<<" expected="<<expected[i]->identity<<" actual_distance="<<actual->distance<<" expected_distance="<<expected[i]->distance<<" delta="<<glm::length(actual->position-expected[i]->position)<<std::endl;assert(actual->identity==expected[i]->identity);assert(glm::length(actual->position-expected[i]->position)<1e-6F);assert(std::abs(actual->distance-expected[i]->distance)<1e-6F);}
            }
            const double indexed=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-before).count();
            assert(hits>0);std::cout<<"PICK_PARITY rep="<<representationName(rep)<<" rays="<<queries.size()<<" hits="<<hits<<" legacy_ms="<<legacy<<" indexed_ms="<<indexed<<std::endl;
        }
        assert(glGetError()==GL_NO_ERROR);
    }
    glfwDestroyWindow(window);glfwTerminate();
}
