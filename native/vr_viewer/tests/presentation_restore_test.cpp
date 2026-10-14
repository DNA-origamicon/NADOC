#include "interaction.hpp"
#include "presentation_restore.hpp"
#include <cassert>
#include <iomanip>
#include <limits>
#include <sstream>

using namespace nadoc_vr;

template<class Action> void rejects(Action action) {
    bool rejected=false;
    try {action();}catch(const std::runtime_error&){rejected=true;}
    assert(rejected);
}

int main() {
    SavedPresentation saved;
    saved.modelToTracking=glm::translate(glm::mat4(1),{.963493F,-.913487F,2.232285F})
        *glm::toMat4(glm::angleAxis(1.13F,glm::normalize(glm::vec3(1,2,-3))))
        *glm::scale(glm::mat4(1),glm::vec3(1.578F));
    saved.sourceCenter={-6.655093F,-6.501067F,-22.248703F};
    saved.normalizationScale=.012443415F;saved.normalizedOffset={0,0,-1.3F};
    const glm::vec3 newCenter{-6.1F,-6.9F,-23.F},newOffset{0,0,-1.3F};
    const float newScale=.0131F;
    const auto restored=saved.forNormalization(newCenter,newScale,newOffset);
    // Independently map source coordinates through the two normalizations.
    for(const auto point:std::array<glm::vec3,5>{{{0,0,0},{20,30,-50},{-30,-20,40},saved.sourceCenter,newCenter}}) {
        const auto expected=saved.modelToTracking*glm::vec4((point-saved.sourceCenter)*saved.normalizationScale+saved.normalizedOffset,1);
        const auto actual=restored*glm::vec4((point-newCenter)*newScale+newOffset,1);
        assert(glm::length(actual-expected)<2.e-6F);
    }
    // Roundtrip establishes row-major interchange and rejects extra/missing data.
    std::ostringstream text;text<<std::setprecision(9)<<"NADOCVR_PRESENTATION 1\n";
    for(int row=0;row<4;++row)for(int col=0;col<4;++col)text<<saved.modelToTracking[col][row]<<' ';
    text<<'\n'<<saved.sourceCenter.x<<' '<<saved.sourceCenter.y<<' '<<saved.sourceCenter.z<<'\n'
        <<saved.normalizationScale<<'\n'<<saved.normalizedOffset.x<<' '<<saved.normalizedOffset.y<<' '<<saved.normalizedOffset.z<<'\n';
    std::istringstream input(text.str());const auto loaded=readSavedPresentation(input);
    assert(glm::length(glm::vec4(loaded.modelToTracking[1]-saved.modelToTracking[1]))<1.e-6F);
    rejects([&]{std::istringstream in(text.str()+"extra");readSavedPresentation(in);});
    rejects([]{std::istringstream in("NADOCVR_PRESENTATION 1 1 0");readSavedPresentation(in);});
    rejects([]{std::istringstream in("NADOCVR_PRESENTATION 2");readSavedPresentation(in);});
    for(int kind=0;kind<6;++kind) {
        auto invalid=glm::mat4(1);
        if(kind==0)invalid[0][0]=std::numeric_limits<float>::quiet_NaN();
        if(kind==1)invalid[0][0]=0;
        if(kind==2)invalid[0][0]=-1;
        if(kind==3)invalid[1][0]=.2F;
        if(kind==4)invalid[0][0]=2;
        if(kind==5)invalid[0][3]=.2F;
        rejects([&]{validatedPresentationScale(invalid);});
    }
    rejects([&]{saved.forNormalization(newCenter,0,newOffset);});
    rejects([&]{saved.forNormalization(newCenter,std::numeric_limits<float>::infinity(),newOffset);});
    // The recovered scale remains coherent when ordinary physical grips resume.
    SceneManipulator manipulator;manipulator.restorePresentation(restored);
    const float scale=manipulator.scale();
    std::array<HandPose,2> hands{};
    hands[1]={true,true,{0,0,0},{1,0,0,0}};manipulator.update(hands);
    hands[1].position={.1F,.2F,.3F};manipulator.update(hands);
    assert(glm::length(glm::vec3(manipulator.transform()[3]-restored[3])-hands[1].position)<1.e-6F);
    hands[1].pressed=false;manipulator.update(hands);
    hands[0]={true,true,{-.1F,0,0},{1,0,0,0}};hands[1]={true,true,{.1F,0,0},{1,0,0,0}};
    manipulator.update(hands);hands[0].position.x=-.2F;hands[1].position.x=.2F;manipulator.update(hands);
    assert(std::abs(manipulator.scale()-2*scale)<1.e-5F);
    const auto before=manipulator.transform();
    rejects([&]{manipulator.restorePresentation(glm::scale(glm::mat4(1),glm::vec3(30)));});
    assert(manipulator.transform()==before);
}
