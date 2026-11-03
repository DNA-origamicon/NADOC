// Actual production GL renderer, isolated from OpenXR and live user sessions.
#define main nadoc_viewer_entry_point
#include "../src/main.cpp"
#undef main
#include <cassert>

int main(int argc, char** argv) {
    if (argc != 4) return 2;
    if (!glfwInit()) return 77;
    glfwWindowHint(GLFW_VISIBLE, GLFW_FALSE);
    glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR, 4);
    glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR, 3);
    auto* window = glfwCreateWindow(768, 768, "CPD representation audit", nullptr, nullptr);
    if (!window) return 77;
    glfwMakeContextCurrent(window);
    glEnable(GL_DEPTH_TEST);
    {
        auto data = loadScene(argv[1]);
        const std::filesystem::path output(argv[2]);
        std::filesystem::create_directories(output);
        std::unordered_set<std::string> atomicLinks;
        std::ifstream links(argv[3]);
        for (std::string line; std::getline(links, line);) atomicLinks.insert(line);
        assert(atomicLinks.size() == 2);
        auto& full = data.representations[representationSourceIndex(Representation::full)];
        glm::vec3 center{};
        int bars = 0;
        for (const auto& c : full.cylinders) if (c.identity.starts_with("cpd:")) {
            center += (c.start+c.end)*.5F; ++bars;
        }
        assert(bars == 2);
        center /= float(bars);
        // Test independent slab rotation and translation using the same function
        // called during production visualization updates.
        SourceIndex index; index.rebuild(full);
        std::unordered_map<std::string, nadoc_vr::VisualizationPoint> frames;
        for (const auto& box : full.boxes) {
            const auto aliases = index.aliases.find(box.identity);
            if (aliases == index.aliases.end()) continue;
            for (const auto& token : aliases->second->tokens) {
                if (!token.starts_with("%5B%22base%22")) continue;
                nadoc_vr::VisualizationPoint f;
                const auto rotation = glm::mat3(glm::rotate(glm::mat4(1), .7F, glm::vec3(0,1,0)));
                f.slabCenter = (box.center+glm::vec3(.1F,.2F,kViewDistanceMeters))/data.normalizationScale+data.normalizationCenter;
                f.slabAxisX = rotation*box.axisX/data.normalizationScale;
                f.slabAxisY = rotation*box.axisY/data.normalizationScale;
                f.slabAxisZ = rotation*box.axisZ/data.normalizationScale;
                frames[token] = f;
            }
        }
        for (const auto& c : full.cylinders) if (c.identity.starts_with("cpd:")) {
            auto offsets = nadoc_vr::cpdVisualizationOffsets(full,index,frames,c,
                data.normalizationCenter,data.normalizationScale,kViewDistanceMeters,{});
            assert(glm::length(offsets.first) > .1F && glm::length(offsets.second) > .1F);
            for (const auto& owner : index.ownership.at(c.identity)->owners) {
                if (!frames.contains(owner.token)) continue;
                for (const auto& box : full.boxes) {
                    const auto aliases=index.aliases.find(box.identity);
                    if (aliases==index.aliases.end() ||
                        std::find(aliases->second->tokens.begin(),aliases->second->tokens.end(),owner.token)==aliases->second->tokens.end()) continue;
                    auto rotated=[&](glm::vec3 p) {
                        return glm::vec3(glm::rotate(glm::mat4(1),.7F,glm::vec3(0,1,0))*glm::vec4(p-box.center,0))
                            +box.center+glm::vec3(.1F,.2F,0);
                    };
                    if(owner.startWeight>0) assert(glm::length(c.start+offsets.first-rotated(c.start))<1e-5F);
                    if(owner.endWeight>0) assert(glm::length(c.end+offsets.second-rotated(c.end))<1e-5F);
                    break;
                }
            }
        }
        GlScene scene(data, true, {}, {}, false);
        auto absent = data;
        for (size_t r=0;r<absent.representations.size();++r) {
            auto& rep=absent.representations[r];
            if (r==representationSourceIndex(Representation::stick) ||
                r==representationSourceIndex(Representation::ballstick))
                assert(std::count_if(rep.cylinders.begin(),rep.cylinders.end(),
                    [&](const auto& c){return atomicLinks.contains(c.identity);}) == 2);
            std::erase_if(rep.cylinders, [&](const auto& c) {
                return c.identity.starts_with("cpd:") || atomicLinks.contains(c.identity);
            });
        }
        GlScene negative(absent, true, {}, {}, false);
        // An explicitly labelled isolated-residue alternate resolves occlusion
        // without replacing or repositioning any molecular primitive.
        std::unordered_set<std::string> endpointTokens;
        for(const auto& c:full.cylinders) if(c.identity.starts_with("cpd:"))
            for(const auto& token:index.aliases.at(c.identity)->tokens) endpointTokens.insert(token);
        auto isolate=[&](SceneData input) {
            for(auto& rep:input.representations) {
                SourceIndex owners;owners.rebuild(rep);
                auto unrelated=[&](const auto& p) {
                    auto it=owners.aliases.find(p.identity);
                    return it==owners.aliases.end() || std::none_of(it->second->tokens.begin(),it->second->tokens.end(),
                        [&](const auto& token){return endpointTokens.contains(token);});
                };
                std::erase_if(rep.points,unrelated);std::erase_if(rep.cylinders,unrelated);
                std::erase_if(rep.halfCylinders,unrelated);std::erase_if(rep.boxes,unrelated);
            }
            return input;
        };
        GlScene isolated(isolate(data),true,{}, {},false);
        GlScene isolatedNegative(isolate(absent),true,{}, {},false);
        auto capture = [&](GlScene& target, Representation rep, glm::mat4 vp, std::string name) {
            target.setStyle(rep, Coloring::strand);
            target.renderShadowMap(glm::mat4(1), {{-.577F,.577F,.577F},{0,1,0}});
            glBindFramebuffer(GL_FRAMEBUFFER,0); glViewport(0,0,768,768); glDrawBuffer(GL_BACK);
            glClearColor(0,0,0,1); glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT);
            target.render(vp,glm::mat4(1),{},false);
            std::vector<unsigned char> rgb(768*768*3);
            glReadPixels(0,0,768,768,GL_RGB,GL_UNSIGNED_BYTE,rgb.data());
            assert(std::count_if(rgb.begin(),rgb.end(),[](auto c){return c>0;}) > 1000);
            if (!name.empty()) {
                std::ofstream file(output/(name+".ppm"),std::ios::binary);
                file << "P6\n768 768\n255\n";
                for (int y=767;y>=0;--y) file.write(reinterpret_cast<char*>(rgb.data()+y*768*3),768*3);
            }
            assert(glGetError()==GL_NO_ERROR);
            return rgb;
        };
        for (size_t i=0;i<kRepresentationCount;++i) {
            const auto rep=static_cast<Representation>(i);
            if (!data.available[representationSourceIndex(rep)]) continue;
            size_t differences=0;
            for (int view=0;view<2;++view) for (int eye=0;eye<2;++eye) {
                auto offset=view==0?glm::vec3(0,0,.25F):glm::vec3(.25F,.12F,.04F);
                auto target=center;
                auto up=glm::vec3(0,1,0);
                const bool isolateView=view==1 && (rep==Representation::full || rep==Representation::stick ||
                    rep==Representation::ballstick || rep==Representation::vdw || rep==Representation::beads);
                const auto name=std::string(kRepresentationNames[i])+
                    (view==0?"-context-":isolateView?"-isolated-":"-alternate-")+std::to_string(eye);
                if(isolateView) {
                    std::vector<StyledCylinder> bonds;
                    for(const auto& c:data.representations[representationSourceIndex(rep)].cylinders)
                        if(c.identity.starts_with("cpd:") || atomicLinks.contains(c.identity)) bonds.push_back(c);
                    assert(bonds.size()==2);
                    target=(bonds[0].start+bonds[0].end+bonds[1].start+bonds[1].end)*.25F;
                    auto normal=glm::normalize(glm::cross(bonds[1].start-bonds[0].start,bonds[0].end-bonds[0].start));
                    if(glm::dot(normal,glm::vec3(-.577F,.577F,.577F))<0) normal=-normal;
                    offset=normal*.06F;
                    if(std::abs(glm::dot(normal,up))>.9F) up={1,0,0};
                }
                offset.x+=(eye==0?-.008F:.008F);
                const auto vp=glm::perspective(glm::radians(60.F),1.F,.005F,100.F)*
                    glm::lookAt(target+offset,target,up);
                const auto pixels=capture(isolateView?isolated:scene,rep,vp,name);
                if (rep==Representation::full || rep==Representation::stick || rep==Representation::ballstick ||
                    rep==Representation::beads || rep==Representation::vdw) {
                    const auto without=capture(isolateView?isolatedNegative:negative,rep,vp,name+"-without-crosslinks");
                    for(size_t p=0;p<pixels.size();++p) differences+=pixels[p]!=without[p];
                }
            }
            if (rep==Representation::full || rep==Representation::stick || rep==Representation::ballstick)
                assert(differences>100);
            if (rep==Representation::beads || rep==Representation::vdw) assert(differences==0);
            std::cout << kRepresentationNames[i] << " crosslink_changed_bytes=" << differences << '\n';
        }
    }
    glfwDestroyWindow(window); glfwTerminate();
}
