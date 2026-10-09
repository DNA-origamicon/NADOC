#define GL_GLEXT_PROTOTYPES
#include <GL/gl.h>
#include "reference_models.hpp"
#include <cassert>
#include <iostream>
#include <thread>

using namespace nadoc_vr;
int main() {
    assert(referenceTriangleHit({0,0,2},{0,0,-1},{-1,-1,0},{1,-1,0},{0,1,0}).value()==2);
    assert(referenceTriangleHit({0,0,-2},{0,0,1},{-1,-1,0},{1,-1,0},{0,1,0}).value()==2);
    assert(!referenceTriangleHit({2,2,2},{0,0,-1},{-1,-1,0},{1,-1,0},{0,1,0}));
    ReferenceModels refs;
    ReferenceMesh mesh;mesh.id="reference";mesh.vertices={{-1,-1,0},{1,-1,0},{0,1,0}};
    refs.models.push_back(mesh);
    std::array<HandPose,2> hands{};hands[1].valid=true;hands[1].position={0,0,2};
    std::array<bool,2> blocked{};
    const glm::mat4 identity(1);
    refs.input(hands,{false,true},{false,true},blocked,identity,0);
    assert(refs.selected=="reference" && blocked[1]);
    hands[1].position.x=.5F;blocked={};
    refs.input(hands,{false,false},{false,true},blocked,identity,.1);
    assert(std::abs(refs.models[0].pose[3].x-.5F)<1e-5F);
    blocked={};refs.input(hands,{false,false},{false,false},blocked,identity,.2);
    assert(refs.hasSelection() && blocked[1]);
    // Second trigger initiates uniform scaling at any surface point, including center.
    blocked={};refs.input(hands,{false,true},{false,true},blocked,identity,.3);
    hands[1].position.y=.2F;blocked={};
    refs.input(hands,{false,false},{false,true},blocked,identity,.4);
    auto pose=refs.models[0].pose;
    const float size=glm::length(glm::vec3(pose[0]));assert(size>1);
    assert(std::abs(size-glm::length(glm::vec3(pose[1])))<1e-5F);
    assert(std::abs(size-glm::length(glm::vec3(pose[2])))<1e-5F);
    blocked={};refs.input(hands,{false,false},{false,false},blocked,identity,.5);
    hands[1].position={10,10,2};blocked={};
    refs.input(hands,{false,true},{false,true},blocked,identity,1);
    assert(!refs.hasSelection());
    // Exact mesh picking respects the world transform and uniform model scale.
    auto world=glm::translate(identity,glm::vec3(10,0,0))*glm::scale(identity,glm::vec3(2));
    hands[1].position={11,0,4};assert(refs.pick(hands[1],world));
    // UI ownership prevents selecting through a panel.
    blocked={false,true};refs.input(hands,{false,true},{false,true},blocked,world,2);
    assert(!refs.hasSelection());
    // File contract carries the source view rotation and is loaded asynchronously.
    const auto directory=std::filesystem::temp_directory_path()/"nadoc-reference-model-test";
    std::filesystem::create_directories(directory);
    const auto eventPath=(directory/"events").string();
    {std::ofstream out(eventPath+".references");out<<"NADOC_REFERENCES 1 7 1\n0 -1 0 1 0 0 0 0 1\nreference\nreference 3 0.5\n1 0 0\n1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1\n-1 -1 0 1 -1 0 0 1 0\n";}
    for(int i=0;i<100 && refs.revision!=7;++i) {
        refs.poll(eventPath,{10,20,30},.01F,{0,0,-1},3+i*.21);
        std::this_thread::sleep_for(std::chrono::milliseconds(2));
    }
    assert(refs.revision==7 && refs.selected=="reference");
    const auto normalized=glm::vec3(refs.normalization*glm::vec4(2,3,4,1));
    assert(glm::distance(normalized,glm::vec3(-.13F,-.18F,-1.26F))<1e-5F);
    assert(refs.wheel.itemCount()==5);
    // Both controllers may grab the surface, then scale and orient it together.
    refs.normalization=identity;refs.models[0].pose=identity;
    hands[0].valid=true;hands[0].position={-.3F,0,2};hands[1].position={.3F,0,2};
    blocked={};refs.input(hands,{true,false},{true,false},blocked,identity,30);
    blocked={};refs.input(hands,{false,true},{true,true},blocked,identity,30.1);
    hands[0].position={0,-.6F,2};hands[1].position={0,.6F,2};
    blocked={};refs.input(hands,{false,false},{true,true},blocked,identity,30.2);
    assert(blocked[0] && blocked[1]);
    const auto rotated=glm::vec3(refs.models[0].pose*glm::vec4(1,0,0,0));
    assert(glm::distance(rotated,glm::vec3(0,2,0))<1e-4F);
    // Drain the asynchronous event writer before removing its scratch directory.
    refs.shutdown();
    std::filesystem::remove(eventPath+".references");
    std::cout<<"Reference picking, persistent selection, move, resize, world scale, UI ownership passed\n";
}
