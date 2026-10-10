// Compile the actual viewer implementation into this test. No alternate parser,
// locator or Extrude model: these checks intentionally exercise production methods.
#define NADOC_SCRYWRITE_TESTING
#define main nadoc_viewer_entry_point
#include "../src/main.cpp"
#undef main

namespace {
void requireLive(bool condition, const char* detail) {
    if (!condition) throw std::runtime_error(detail);
}
#include "representation_shadow_check.hpp"
struct LiveViewerTest {
    static void verifyQuiverReactivation() {
        Viewer v(SceneData{});
        std::istringstream script("SCRYWRITE_WITNESS 1\nstep 100\n");
        v.witness_.emplace(nadoc_vr::scrywrite::WitnessReplay::load(script));
        v.sessionState_=XR_SESSION_STATE_FOCUSED;
        v.witnessObserverPosition_={0,1.6F,0};v.witnessObserverOrientation_={1,0,0,0};
        const auto holster=glm::rotation(glm::vec3(0,0,-1),glm::normalize(glm::vec3(0,1,1)));
        auto pose=[&](size_t h,bool behind) {
            v.hands_[h]={true,false,v.witnessObserverPosition_+glm::vec3(h?.28F:-.28F,behind?.08F:-.1F,behind?.28F:-.4F),behind?holster:glm::quat(1,0,0,0)};
            v.processQuiver(true,0);
        };
        auto reach=[&](size_t h) {pose(h,false);pose(h,true);};
        v.sidebarMenus_.menus[0].open=v.sidebarMenus_.menus[1].open=true;
        v.bendPanel_.active=true;v.triggerPartial_[1]=true;
        reach(0);
        requireLive(v.viewTools_.open && !v.viewTools_.placement.worldDocked() && !v.ligation_.nickActive,
                    "Other-hand tool/button or open sidebar suppressed left quiver");
        const auto behind=v.viewTools_.position;
        v.hands_[0].position.z=.05F;v.processQuiver(true,0);
        requireLive(!v.viewTools_.placement.worldDocked() && v.viewTools_.position!=behind,"Tablet did not follow the hand out of holster");
        pose(0,false);
        requireLive(!v.viewTools_.placement.worldDocked(),"Returning in front automatically docked tablet");
        const auto followed=v.viewTools_.position;
        const auto facing=v.viewTools_.orientation;
        v.hands_[0].position.x-=.1F;
        v.hands_[0].orientation=glm::angleAxis(.2F,glm::vec3(0,1,0));
        v.processQuiver(true,0);
        requireLive(v.viewTools_.position!=followed && v.viewTools_.orientation!=facing,
                    "Tablet stopped following controller position or rotation");
        auto clickDock=[&]() {
            auto pointers=v.hands_;pointers[1].valid=true;
            pointers[1].position=v.viewTools_.world({184.F/768,652.F/768})+v.viewTools_.orientation*glm::vec3(0,0,.2F);
            pointers[1].orientation=v.viewTools_.orientation;
            std::array<bool,2> blocked{};
            v.viewTools_.input(pointers,{false,true},blocked,[](size_t){});
            requireLive(blocked[1],"Dock control was not interactive while following");
        };
        clickDock();
        requireLive(v.viewTools_.placement.worldDocked(),"Dock button did not freeze tablet");
        const auto docked=v.viewTools_.position;
        v.hands_[0].position.x-=.1F;v.processQuiver(true,0);
        requireLive(v.viewTools_.position==docked,"Docked tablet kept following the controller");
        clickDock();
        requireLive(!v.viewTools_.placement.worldDocked(),"Follow button did not restore controller attachment");
        const auto reattached=v.viewTools_.position;
        v.hands_[0].position.x+=.1F;v.processQuiver(true,0);
        requireLive(v.viewTools_.position!=reattached,"Follow button attached tablet to clicking hand instead of left hand");
        clickDock();
        reach(0);requireLive(!v.viewTools_.open,"Reach-back did not dismiss fixed tablet");
        reach(0);requireLive(v.viewTools_.open && !v.viewTools_.placement.worldDocked(),"Reopened tablet did not start following");
        v.triggerPartial_[1]=false;
        reach(1);
        requireLive(!v.ligation_.nickActive && v.bendPanel_.active &&
                    std::string(v.quiverBlocked_[1])=="finish_modeling_tool","Quiver changed or confirmed unfinished Bend");
        v.bendPanel_.exit(v.sidebarMenus_.menus);
        reach(1);
        requireLive(v.ligation_.nickActive && v.sidebarMenus_.menus[1].open,"Scissors did not reactivate after tool exit with sidebar open");
        const auto sequence=v.quiver_.sequence;
        v.processQuiver(true,0);v.processQuiver(true,0);
        requireLive(v.quiver_.sequence==sequence,"Held holster repeated");
        v.ligation_.waiting=true;reach(1);
        requireLive(v.ligation_.nickActive && std::string(v.quiverBlocked_[1])=="pending_edit","Pending Nick did not block another edit");
        reach(0);requireLive(!v.viewTools_.open,"Pending Nick blocked left panel stow");
        v.ligation_.waiting=false;reach(1);
        requireLive(!v.ligation_.nickActive,"Acknowledged Nick did not rearm");
        v.sweepPanel_.active=true;v.sweepDraft_.step=2;
        const auto points=v.sweepDraft_.pointsNm.size();reach(1);
        requireLive(v.sweepDraft_.pointsNm.size()==points && !v.ligation_.nickActive,"Shoulder gesture added a Sweep point");
        v.sweepPanel_.exit(v.sidebarMenus_.menus);reach(1);
        requireLive(v.ligation_.nickActive,"Sweep exit did not restore scissors access");
        pose(1,false);v.hands_[1].valid=false;v.processQuiver(true,0);pose(1,true);
        requireLive(v.ligation_.nickActive,"Tracking loss triggered an unarmed reach");
        reach(1);requireLive(!v.ligation_.nickActive,"Tracking recovery did not rearm");
        v.inputResumeBlocked_[0]=true;reach(0);
        requireLive(!v.viewTools_.open && std::string(v.quiverBlocked_[0])=="release_after_focus","Focus-release guard bypassed");
        v.inputResumeBlocked_[0]=false;reach(0);
        requireLive(v.viewTools_.open,"Focus-release recovery left tablet disabled");
        requireLive(v.liveState().find("\"blocked\":[")!=std::string::npos,"Quiver blockers missing from inspector");
    }
    static void verifyViewToolsDismissal() {
        for(size_t hand:{0U,1U})for(bool trigger:{false,true}) {
            Viewer v(SceneData{});
            std::istringstream script("SCRYWRITE_WITNESS 1\nstep 100\n");
            v.witness_.emplace(nadoc_vr::scrywrite::WitnessReplay::load(script));
            v.sessionState_=XR_SESSION_STATE_FOCUSED;
            v.witnessObserverPosition_={0,1.6F,0};v.witnessObserverOrientation_={1,0,0,0};
            auto& t=v.viewTools_;t.open=true;t.placement.openDocked({0,1.5F,-.7F},{1,0,0,0});t.syncPose();
            auto& h=v.hands_[hand];h.valid=true;h.orientation={1,0,0,0};
            const auto b=VRViewTools::panelBounds();
            h.position=t.placement.worldPoint({b.maximum.x,0,trigger?.3F:0.F});
            if(trigger) {
                std::array<bool,2> buttons{};buttons[hand]=true;
                v.remotePanels_.update(v.remotePanelTargets(),v.hands_,buttons,buttons,v.witnessObserverPosition_,0);
                requireLive(v.remotePanels_.active==&t.placement,"View tablet did not use shared trigger border controller");
                const auto before=t.placement.position();h.position.x+=.05F;
                v.remotePanels_.update(v.remotePanelTargets(),v.hands_,{},buttons,v.witnessObserverPosition_,1);
                requireLive(glm::distance(t.placement.position(),before+glm::vec3(.05F,0,0))<1e-5F,"Trigger border movement differs from hand movement");
                v.triggerPartial_[hand]=v.triggerPressed_[hand]=true;
            } else {
                h.pressed=true;v.gripPressed_[hand]=true;
                requireLive(t.placement.beginDrag(hand,v.hands_,b.minimum,b.maximum),"Grip border grab failed");
            }
            h.position=v.witnessObserverPosition_+glm::vec3(hand?.28F:-.28F,-.1F,-.4F);
            v.processQuiver(true,0);
            requireLive(v.quiver_.armed[hand],"Held tablet did not arm shoulder dismissal");
            h.position=v.witnessObserverPosition_+glm::vec3(hand?.28F:-.28F,.08F,.28F);
            h.orientation=glm::rotation(glm::vec3(0,0,-1),glm::normalize(glm::vec3(0,1,1)));
            v.processQuiver(true,0);
            requireLive(!t.open && !v.remotePanels_.active && !t.placement.dragHand() && !v.ligation_.nickActive,
                        "Held tablet shoulder dismissal leaked a grab or equipped scissors");
        }
        Viewer v(SceneData{});auto& t=v.viewTools_;t.open=true;
        t.placement.openDocked({0,0,-1},{1,0,0,0});t.syncPose();
        for(size_t hand:{0U,1U}) {
            v.hands_={};auto& h=v.hands_[hand];h.valid=true;h.orientation=t.orientation;
            const auto target=t.world({682.F/768,30.F/768});h.position=target+glm::vec3(0,0,.4F);
            requireLive(t.rayEndpoint(h) && glm::distance(*t.rayEndpoint(h),target)<1e-5F,"Tablet pointer beam misses close control");
            std::array<bool,2> clicked{},blocked{};
            t.input(v.hands_,clicked,blocked,[](size_t){});
            requireLive(t.closeHover[hand],"Close control did not expose pointer hover");
            clicked[hand]=true;blocked={};
            t.input(v.hands_,clicked,blocked,[](size_t){throw std::runtime_error("Close committed visualization");});
            requireLive(!t.open && blocked[hand] && !t.rayEndpoint(h),"Close button failed or left a beam visible");
            t.open=true;
        }
    }
    static void verifyNickCatalog() {
        Viewer v(SceneData{});
        v.ligation_.version=7;
        v.ligation_.bonds={{{1,2,3},{4,5,6},{},{}}};
        requireLive(v.liveState().find("\"bonds_omitted\":true")!=std::string::npos,"Inactive Nick serialized targets");
        const auto sequence=v.liveCommandSequence_;
        const auto full=v.liveCommand("observe targets");
        requireLive(full.find("\"bonds_omitted\":false")!=std::string::npos &&
                    full.find("\"a\":[1,2,3]")!=std::string::npos,"Explicit bond catalog unavailable");
        requireLive(v.liveCommandSequence_==sequence,"Read-only catalog changed command sequence");
        v.ligation_.nickActive=true;
        const auto first=v.liveBondCatalog_;
        requireLive(v.liveState(true).find(first)!=std::string::npos,"Active Nick omitted cached targets");
        v.ligation_.bonds[0].a.x=9;++v.ligation_.version;
        requireLive(v.liveState(true).find("\"a\":[9,2,3]")!=std::string::npos,"Changed targets reused old catalog");
        const auto changed=v.liveBondCatalog_;
        v.manipulator_.placeInView({0,1,0},glm::quat(1,0,0,0));
        v.liveState(true);
        requireLive(v.liveBondCatalog_!=changed,"Model movement reused old world positions");
    }
    static void verifyViewToolsFrameSeam() {
        Viewer v(SceneData{});
        auto& tools=v.viewTools_;
        tools.open=true;tools.version=1;
        const auto facing=glm::angleAxis(.35F,glm::vec3(0,1,0));
        tools.placement.openDocked({.2F,.1F,-1.2F},facing);
        tools.placement.setScale(.8F);tools.syncPose();
        const auto bounds=VRViewTools::panelBounds();
        const auto targets=v.remotePanelTargets();
        const auto remote=std::find_if(targets.begin(),targets.end(),[&](const auto& p){
            return p.placement==&tools.placement;
        });
        requireLive(remote!=targets.end() && remote->border.minimum==bounds.minimum &&
                    remote->border.maximum==bounds.maximum && remote->surface.minimum==bounds.minimum &&
                    remote->surface.maximum==bounds.maximum,"Remote ViewTools bounds differ from its local frame");
        // Golden content coordinates from the original 768px tablet. Enlarging
        // its separate grip frame must not move any icon or controller hit.
        constexpr std::array<glm::vec2,8> centers{{
            {-.16972222F,.24555556F},{.16972222F,.24555556F},
            {-.16972222F,.14444444F},{.16972222F,.14444444F},
            {-.16972222F,.04333333F},{.16972222F,.04333333F},
            {-.16972222F,-.05777778F},{.16972222F,-.05777778F}}};
        std::array<nadoc_vr::HandPose,2> hands{};
        hands[1].valid=true;hands[1].orientation=facing;
        for(size_t i=0;i<centers.size();++i) {
            const auto world=tools.placement.worldPoint({centers[i],0});
            requireLive(glm::distance(tools.world(VRViewTools::cell(i)),world)<1e-6F,
                        "ViewTools icon moved when its grip frame changed");
            hands[1].position=world+facing*glm::vec3(0,0,.4F);
            const auto uv=tools.hit(hands[1]);
            requireLive(uv && glm::distance(*uv,VRViewTools::cell(i))<1e-5F,
                        "ViewTools icon ray missed its unchanged center");
            std::array<bool,2> blocked{};size_t commits=0;
            tools.waiting=false;
            tools.input(hands,{false,true},blocked,[&](size_t hand){
                requireLive(hand==1,"ViewTools changed input hand");++commits;
            });
            requireLive(blocked[1] && commits==1 && tools.requested==int(i) &&
                        tools.hover[1]==int(i) && tools.sequence==i+1,
                        "ViewTools center activated the wrong icon or leaked input");
        }
        hands[1].position=tools.placement.worldPoint({bounds.maximum.x,0,.4F});
        requireLive(!tools.hit(hands[1]),"ViewTools grip rail maps to an icon hit");
        hands[1].position=tools.placement.worldPoint({bounds.maximum.x,0,0});
        hands[1].pressed=true;
        std::array<bool,2> blocked{};
        tools.grips(hands,{false,true},blocked,[](size_t,float){});
        requireLive(blocked[1] && tools.placement.dragHand()==1,"ViewTools enlarged local border cannot grab");
        const auto previous=tools.placement.position();
        hands[1].position.x+=.1F;blocked={};
        tools.grips(hands,{},blocked,[](size_t,float){});
        requireLive(glm::distance(tools.placement.position(),previous+glm::vec3(.1F,0,0))<1e-5F,
                    "ViewTools border grab did not move the tablet");
        hands[1].pressed=false;blocked={};
        tools.grips(hands,{},blocked,[](size_t,float){});
        requireLive(!tools.placement.dragHand(),"Released ViewTools grip stayed latched");
        tools.open=false;
        const auto closedTargets=v.remotePanelTargets();
        requireLive(std::none_of(closedTargets.begin(),closedTargets.end(),[&](const auto& p){
            return p.placement==&tools.placement;
        }),"Closed ViewTools retained a remote grip target");
    }
    static void verifySidebarSpawnView() {
        auto witness=[](Viewer& v) {
            std::istringstream script("SCRYWRITE_WITNESS 1\nhead 1 2 3 0.70710678 0 0.70710678 0\nstep 100\n");
            v.witness_.emplace(nadoc_vr::scrywrite::WitnessReplay::load(script));
            v.witness_->advance({});
            v.hands_[0]={true,false,{-.4F,1.1F,-.2F},glm::angleAxis(.2F,glm::vec3(0,1,0))};
            v.hands_[1]={true,false,{.4F,1.2F,-.3F},glm::angleAxis(-.3F,glm::vec3(0,1,0))};
            v.witnessObserverPosition_={-3,.5F,4};
            v.witnessObserverOrientation_={1,0,0,0};
        };
        auto verify=[](const Viewer& v,size_t hand) {
            const auto& menu=v.sidebarMenus_.menus[hand];
            const auto position=v.hands_[hand].position;
            auto orientation=v.hands_[hand].orientation;
            const auto expected=position+orientation*glm::vec3(0,0,-.40F);
            orientation=glm::normalize(orientation*glm::angleAxis(glm::radians(-30.F),glm::vec3(1,0,0)));
            requireLive(menu.open && glm::distance(menu.placement.position(),expected)<1e-5F &&
                        std::abs(glm::dot(menu.placement.orientation(),orientation))>1.F-1e-5F,
                        "Sidebar spawned relative to the wrong controller pose");
        };
        for(size_t hand:{0U,1U})for(bool scripted:{false,true}) {
            Viewer v(SceneData{});
            v.hands_[0]={true,false,{-.4F,1.1F,-.2F},glm::angleAxis(.2F,glm::vec3(0,1,0))};
            v.hands_[1]={true,false,{.4F,1.2F,-.3F},glm::angleAxis(-.3F,glm::vec3(0,1,0))};
            v.witnessObserverPosition_={-3,.5F,4};
            v.witnessObserverOrientation_=glm::angleAxis(.3F,glm::vec3(0,1,0));
            if(scripted)witness(v);
            v.toggleSidebar(hand);
            verify(v,hand);
        }
        for(size_t hand:{0U,1U})for(bool tabRoute:{false,true}) {
            Viewer v(SceneData{});witness(v);
            if(tabRoute)v.openSidebarTab(hand,hand==0?"vr":"tools");
            else v.toggleMenu(hand);
            verify(v,hand);
        }
        for(size_t tool=0;tool<4;++tool) {
            Viewer v(SceneData{});witness(v);v.selectedSelectionKind_="cluster";
            v.activateAuthoringTool(tool);
            verify(v,1);
        }
    }
    static void verifyRadialHistoryAndCurrentPanels() {
        // Record the real pulse request while witness mode suppresses OpenXR IO.
        auto witness=[](Viewer& v) {
            std::istringstream script("SCRYWRITE_WITNESS 1\nstep 100\n");
            v.witness_.emplace(nadoc_vr::scrywrite::WitnessReplay::load(script));
            v.ligation_.version=7;
        };
        for(size_t action:{2U,3U})for(bool open:{false,true}) {
            Viewer v(SceneData{});witness(v);
            if(open) {
                v.activateAuthoringTool(0);
                v.sidebarMenus_.menus[0].open=true;
                v.desktopPanel_.open=v.viewTools_.open=true;
            }
            const auto mode=v.toolShell_.mode();
            const auto configuration=v.toolConfig_.mode();
            const auto rightTab=v.sidebarMenus_.menus[1].tab().key;
            v.activateRadialEdit(action);
            requireLive(v.ligation_.sequence==1 && v.ligation_.waiting &&
                        v.ligation_.committedAction==(action==2?"undo":"redo") &&
                        v.ligation_.committedVersion==7,"Radial history did not publish the requested command");
            requireLive(v.hapticRequests_[0]==0 && v.hapticRequests_[1]==1 &&
                        v.hapticAmplitude_[1]>.5F,"Radial history did not confirm once on the right controller");
            requireLive(v.sidebarMenus_.menus[0].open==open && v.sidebarMenus_.menus[1].open==open &&
                        v.extrudePanel_.active==open && v.latticeOpen_==open &&
                        v.desktopPanel_.open==open && v.viewTools_.open==open &&
                        !v.movePanel_.active && !v.bendPanel_.active && !v.volumePanel_.active &&
                        !v.dimensionPanel_.tool.active && v.radialToolMenu_.pending()==action,
                        "Radial history opened or replaced an interface");
            requireLive(v.toolShell_.mode()==mode && v.toolConfig_.mode()==configuration &&
                        v.sidebarMenus_.menus[1].tab().key==rightTab,
                        "Radial history changed the active tool or its sidebar");
            const auto state=v.liveState();
            requireLive(state.find("\"haptic_requests\":[0,1]")!=std::string::npos,
                        "History confirmation is missing from live evidence");
            v.activateRadialEdit(action);
            requireLive(v.ligation_.sequence==1 && v.hapticRequests_[1]==1,
                        "Pending history replayed the command or confirmation");
        }
        for(size_t item=0;item<4;++item) {
            Viewer v(SceneData{});witness(v);v.selectedSelectionKind_="cluster";
            v.activateAuthoringTool(item);
            const auto tab=v.sidebarMenus_.menus[1].tab().key;
            nadoc_vr::ToolExecutionFeedback feedback;
            feedback.mode=nadoc_vr::toolModeName(v.toolShell_.mode());
            feedback.action="confirm";feedback.status="succeeded";
            v.toolShell_.applyExecutionFeedback(feedback);
            const auto action=tab+":undo";
            v.activateSidebarAction(action,0);
            requireLive(v.toolShell_.executionPending() && v.toolShell_.status()=="UNDOING" &&
                        v.hapticRequests_[0]==1 && v.hapticRequests_[1]==0,
                        "Tool-panel Undo did not dispatch and vibrate the activating controller");
            requireLive(v.sidebarMenus_.menus[1].open && v.sidebarMenus_.menus[1].tab().key==tab &&
                        !v.sidebarMenus_.menus[0].open,"Tool-panel Undo replaced its current sidebar");
            v.activateSidebarAction(action,0);
            requireLive(v.hapticRequests_[0]==1,"Pending tool Undo repeated its confirmation");
        }
        {
            Viewer v(SceneData{});witness(v);v.ligation_.version=0;
            v.activateRadialEdit(2);
            requireLive(v.ligation_.sequence==0 && v.hapticRequests_[1]==0 && !v.sidebarMenus_.anyOpen(),
                        "Unavailable Undo confirmed or opened a menu");
        }
        {
            Viewer v(SceneData{});witness(v);v.selectedSelectionKind_="cluster";
            v.activateAuthoringTool(3);
            nadoc_vr::ToolExecutionFeedback feedback;feedback.mode="move_rotate";
            feedback.action="confirm";feedback.status="succeeded";
            v.toolShell_.applyExecutionFeedback(feedback);
            auto& menu=v.sidebarMenus_.menus[1];
            menu.placement.openDocked({0,0,-1},{1,0,0,0});
            const auto controls=menu.controls(false);
            const auto undo=std::find_if(controls.begin(),controls.end(),[](const auto& c){return c.id=="move:undo";});
            requireLive(undo!=controls.end(),"Move Undo control missing");
            v.hands_[0].valid=true;v.hands_[0].orientation={1,0,0,0};
            const auto center=(undo->bounds.minimum+undo->bounds.maximum)*.5F;
            v.hands_[0].position=menu.placement.worldPoint({center,.4F});
            const auto blocked=v.sidebarMenus_.input(v.hands_,{true,false},{true,false},{},
                {1e9F,1e9F},0,[&](const std::string& action,size_t hand){v.activateSidebarAction(action,hand);});
            requireLive(blocked[0] && v.toolShell_.status()=="UNDOING" &&
                        v.hapticRequests_[0]==2 && v.hapticRequests_[1]==0 && v.hapticAmplitude_[0]>.5F,
                        "Cross-hand Undo confirmed the panel owner instead of the activating controller");
            requireLive(menu.open && menu.tab().key=="move" && !v.sidebarMenus_.menus[0].open,
                        "Cross-hand Undo opened another menu");
        }
        for(size_t item:{0U,1U}) {
            Viewer v(SceneData{});witness(v);v.selectionLevel_="cluster";
            v.activateRadialEdit(item);
            requireLive(v.ligation_.active==(item==0) && v.ligation_.nickActive==(item==1) &&
                        v.selectionLevel_==(item==0?"end":"base"),"Radial edit did not select its current mode");
            requireLive(!v.sidebarMenus_.anyOpen() && !v.latticeOpen_ && !v.desktopPanel_.open &&
                        !v.viewTools_.open,"Radial selection opened a menu");
            v.activateRadialEdit(item);
            requireLive(!v.ligation_.active && !v.ligation_.nickActive && v.selectionLevel_=="cluster" &&
                        !v.sidebarMenus_.anyOpen(),"Radial toggle did not restore selection without a menu");
        }
        for(const auto& route:std::array<std::pair<const char*,const char*>,4>{{
                {"options","vr"},{"tools","tools"},{"settings","tools"},{"jobs","dynamics"}}}) {
            Viewer v(SceneData{});witness(v);
            v.activateSidebarAction(route.first,1);
            const size_t hand=std::string(route.second)=="tools"?1:0;
            requireLive(v.sidebarMenus_.menus[hand].open &&
                        v.sidebarMenus_.menus[hand].tab().key==route.second &&
                        !v.sidebarMenus_.menus[1-hand].open,"Navigation did not route to the current sidebar tab");
            requireLive(std::string(v.menuPageName())=="sidebars","Current sidebar reported an obsolete menu page");
        }
        for(size_t i=0;i<6;++i) {
            Viewer v(SceneData{});witness(v);v.hands_[0].valid=true;
            auto input=[&](bool pressed,glm::vec2 axis){v.selectionWheel_.input(pressed,axis,v.hands_[0],true,
                [&](const char* level){v.publishSelectionLevel(level);},[&](float amount){v.pulse(0,amount);});};
            input(true,{0,0});input(true,nadoc_vr::SelectionWheel::direction(i));
            requireLive(v.levelSequence_==0 && v.hapticRequests_[0]==1,"Wheel committed before release or missed hover pulse");
            input(false,{0,0});
            requireLive(v.selectionLevel_==nadoc_vr::SelectionWheel::levels[i] && v.levelSequence_==1 &&
                        v.hapticRequests_[0]==2 && v.hapticRequests_[1]==0 && !v.sidebarMenus_.anyOpen(),
                        "Selection wheel did not publish exactly once on release without opening menus");
            v.activateSidebarAction("select:cluster",1);
            requireLive(v.levelSequence_==1,"Removed menu selection route still active");
        }
        Viewer v(SceneData{});witness(v);v.activateAuthoringTool(3);
        v.activateSidebarAction("unknown:action",1);
        requireLive(v.movePanel_.active && v.sidebarMenus_.menus[1].open &&
                    v.sidebarMenus_.menus[1].tab().key=="move" && !v.sidebarMenus_.menus[0].open,
                    "Unknown action replaced the current panel");
    }
    static void verifyTrajectoryLauncherWithBothSidebars() {
        for(size_t hand:{0U,1U})for(bool selected:{false,true}) {
            Viewer v(SceneData{});
            std::istringstream script("SCRYWRITE_WITNESS 1\nstep 100\n");
            v.witness_.emplace(nadoc_vr::scrywrite::WitnessReplay::load(script));
            v.witnessObserverPosition_={0,1.6F,0};
            v.simulationPanel_.bind(v.sidebarMenus_.menus[0],&v.sidebarMenus_.menus[1]);
            v.simulationPanel_.selected=selected;
            v.openSidebarTab(0,"dynamics");
            v.sidebarMenus_.toggle(1,v.witnessObserverPosition_,v.witnessObserverOrientation_);
            auto& left=v.sidebarMenus_.menus[0];
            auto& right=v.sidebarMenus_.menus[1];
            const auto controls=left.controls(false);
            const auto launcher=std::find_if(controls.begin(),controls.end(),[](const auto& c){return c.id=="sim:trajectory";});
            requireLive(launcher!=controls.end(),"Simulations trajectory launcher missing");
            const auto center=(launcher->bounds.minimum+launcher->bounds.maximum)*.5F;
            v.hands_[hand].valid=true;v.hands_[hand].orientation=left.placement.orientation();
            v.hands_[hand].position=left.placement.worldPoint({center,.4F});
            v.triggerClicked_[hand]=v.triggerPressed_[hand]=true;
            const auto before=right.placement.position();
            const auto remote=v.remotePanels_.update(v.remotePanelTargets(),v.hands_,
                v.triggerClicked_,v.triggerPressed_,v.witnessObserverPosition_,0);
            requireLive(!remote[hand] && !v.remotePanels_.active && right.placement.position()==before,
                        "Default adjacent sidebar border stole the trajectory launcher click");
            const auto blocked=v.sidebarMenus_.input(v.hands_,v.triggerClicked_,v.triggerPressed_,remote,
                {1e9F,1e9F},0,[&](const std::string& action,size_t actor){v.activateSidebarAction(action,actor);});
            requireLive(blocked[hand] && v.trajectoryPanel_.active && left.tab().key=="trajectory" &&
                        left.open && right.open,"Trajectory launcher was unreachable with both default sidebars open");
        }
    }
    static void verifyTrajectorySidebar(const std::string& directory) {
        Viewer v(SceneData{},directory+"/trajectory-events.json");
        std::istringstream script("SCRYWRITE_WITNESS 1\nstep 100\n");
        v.witness_.emplace(nadoc_vr::scrywrite::WitnessReplay::load(script));
        v.trajectoryState_.active=true;v.trajectoryState_.frameCount=11;v.trajectoryState_.frameIndex=5;
        v.activateSidebarAction("trajectory",1);
        auto& menu=v.sidebarMenus_.menus[0];
        requireLive(v.trajectoryPanel_.active && menu.open && menu.tab().key=="trajectory" &&
                    !v.sidebarMenus_.menus[1].open,"Playback did not open the current left sidebar panel");
        v.activateSidebarAction("trajectory:play",1);
        requireLive(v.trajectoryAction_=="play" && v.trajectoryRequestSequence_==1,"Playback command not published");
        v.trajectoryState_.playing=true;v.activateSidebarAction("trajectory:play",1);
        requireLive(v.trajectoryAction_=="pause" && v.trajectoryRequestSequence_==2,"Pause command not published");
        v.activateSidebarAction("trajectory:previous",1);
        requireLive(v.trajectoryAction_=="seek" && v.trajectoryRequestedFrameIndex_==4,"Previous frame not published");
        v.activateSidebarAction("trajectory:next",1);
        requireLive(v.trajectoryRequestedFrameIndex_==6,"Next frame not published");
        v.trajectoryState_.frameIndex=0;v.activateSidebarAction("trajectory:previous",1);
        requireLive(v.trajectoryRequestedFrameIndex_==0,"Previous frame underflowed");
        v.trajectoryState_.frameIndex=10;v.activateSidebarAction("trajectory:next",1);
        requireLive(v.trajectoryRequestedFrameIndex_==10,"Next frame overflowed");
        menu.placement.openDocked({0,0,-1},{1,0,0,0});
        const auto controls=menu.controls(false);
        const auto seek=std::find_if(controls.begin(),controls.end(),[](const auto& c){return c.id=="trajectory:seek";});
        requireLive(seek!=controls.end(),"Playback seek control missing");
        auto& hand=v.hands_[1];hand.valid=true;hand.orientation={1,0,0,0};
        const float y=(seek->bounds.minimum.y+seek->bounds.maximum.y)*.5F;
        const float middle=(seek->bounds.minimum.x+seek->bounds.maximum.x)*.5F;
        hand.position=menu.placement.worldPoint({middle,y,.4F});
        v.triggerPressed_[1]=v.triggerClicked_[1]=true;
        const auto before=v.trajectoryRequestSequence_;
        for(const float x:{seek->bounds.minimum.x-.04F,seek->bounds.maximum.x+.04F}) {
            hand.position=menu.placement.worldPoint({x,y,.4F});
            requireLive(!v.processTrajectoryInput({},{1e9F,1e9F})[1] && !v.trajectoryScrubHand_ &&
                        v.trajectoryRequestSequence_==before,
                        "Blank space outside the visible timeline started a seek");
        }
        hand.position=menu.placement.worldPoint({middle,y,.4F});
        menu.focus.begin("trajectory:play","");
        requireLive(!v.processTrajectoryInput({},{1e9F,1e9F})[1] &&
                    v.trajectoryRequestSequence_==before,"Cross-hand ray stole focused playback input");
        menu.focus.reset();
        requireLive(!v.processTrajectoryInput({},{1e9F,.1F})[1] &&
                    v.trajectoryRequestSequence_==before,"Seek leaked through a foreground panel");
        requireLive(v.processTrajectoryInput({},{1e9F,1e9F})[1] && v.trajectoryScrubHand_==1 &&
                    v.trajectoryRequestedFrameIndex_==5 && v.trajectoryRequestSequence_==before+1,
                    "Production ray did not acquire and publish timeline seek");
        v.triggerClicked_[1]=false;
        v.processTrajectoryInput({},{1e9F,1e9F});
        requireLive(v.trajectoryRequestSequence_==before+1,"Stationary held seek published repeatedly");
        hand.position=menu.placement.worldPoint({seek->bounds.maximum.x,y,.4F});
        v.processTrajectoryInput({},{1e9F,1e9F});
        requireLive(v.trajectoryRequestedFrameIndex_==10 && v.trajectoryRequestSequence_==before+2,
                    "Held timeline drag did not reach the last frame");
        v.processTrajectoryInput({false,true},{1e9F,1e9F});
        requireLive(!v.trajectoryScrubHand_,"Blocked timeline retained the trigger");
        v.triggerClicked_[1]=true;v.processTrajectoryInput({},{1e9F,1e9F});
        v.triggerPressed_[1]=false;v.processTrajectoryInput({},{1e9F,1e9F});
        requireLive(!v.trajectoryScrubHand_,"Released timeline retained the trigger");
        v.trajectoryState_.active=false;
        const auto inactive=v.trajectoryRequestSequence_;v.activateSidebarAction("trajectory:play",1);
        requireLive(v.trajectoryRequestSequence_==inactive,"Inactive trajectory accepted playback command");
        v.activateSidebarAction("trajectory:back",1);
        requireLive(!v.trajectoryPanel_.active && menu.open && menu.tab().key=="dynamics" &&
                    !menu.customTab && !v.sidebarMenus_.menus[1].open,
                    "Playback Back did not restore the current Simulations sidebar");
    }
    static void verifyVRTabActions() {
        Viewer v(SceneData{});
        auto& left=v.sidebarMenus_.menus[0];
        const auto tab=std::find_if(left.tabs.begin(),left.tabs.end(),[](auto i){return nadoc_vr::kSidebarTabs[i].key=="vr";});
        requireLive(tab!=left.tabs.end(),"Left VR tab missing");
        left.selected=static_cast<size_t>(tab-left.tabs.begin());left.open=true;
        auto activate=[&](const std::string& id) {
            const auto controls=left.controls();
            const auto c=std::find_if(controls.begin(),controls.end(),[&](const auto& item){return item.id==id;});
            requireLive(c!=controls.end()&&c->enabled,"VR control unavailable");
            v.activateSidebarAction(left.activate(*c),0);
        };
        requireLive(!v.shadowLight_.headFollowing() && !v.witnessShadowLight_.headFollowing(),
                    "Head-following lighting must default off");
        activate("vr-head-light");
        requireLive(v.shadowLight_.headFollowing() && v.witnessShadowLight_.headFollowing(),
                    "VR lighting toggle did not enable both views");
        activate("vr-head-light");
        requireLive(!v.shadowLight_.headFollowing() && !v.witnessShadowLight_.headFollowing() && left.open,
                    "VR lighting toggle did not disable or closed sidebar");
        v.hands_[0]={true,false,{.2F,1.1F,-.3F},glm::angleAxis(.4F,glm::vec3(0,1,0))};
        activate("vr-desktop");
        requireLive(glm::distance(v.desktopPanel_.placement.position(),v.hands_[0].position+
            v.hands_[0].orientation*glm::vec3(0,0,-1.35F))<1e-5F,"Desktop ignored invoking controller");
        requireLive(left.open&&v.desktopPanel_.open,"Desktop must pop out independently of sidebar");
        const auto b=v.desktopPanel_.content(),c=v.desktopPanel_.closeBounds();
        requireLive(c.minimum.y>v.desktopPanel_.bounds().maximum.y && c.minimum.y>b.maximum.y,"Close overlaps desktop pixels or outer frame");
        v.desktopPanel_.placement.openDocked({0,0,-1},glm::quat(1,0,0,0));
        v.hands_[1].valid=true;v.hands_[1].orientation=glm::quat(1,0,0,0);
        v.hands_[1].position=v.desktopPanel_.placement.worldPoint({0,0,0})+glm::vec3(0,0,.4F);
        v.triggerValues_[1]=.4F;v.triggerPartial_[1]=true;
        requireLive(v.processDesktopInput({})[1]&&v.desktopPanel_.magnifying,"Partial trigger must magnify desktop");
        v.triggerPressed_[1]=true;v.processDesktopInput({});
        requireLive(!v.desktopPanel_.magnifying,"Full trigger must leave lens mode");
        v.triggerPartial_[1]=v.triggerPressed_[1]=false;v.triggerValues_[1]=0;v.processDesktopInput({});
        requireLive(!v.desktopPanel_.magnifying,"Released trigger retained magnifier");
        std::array<bool,2> grips{};
        const auto frame=v.desktopPanel_.bounds();
        v.hands_[1].position=v.desktopPanel_.placement.worldPoint({frame.maximum.x,0,0})+glm::vec3(0,0,.12F);v.hands_[1].pressed=true;
        v.desktopPanel_.grips(nadoc_vr::MenuPlacement::borderContacts(v.hands_,{.025F,.025F}),{false,true},grips,[](size_t,float){});
        requireLive(grips[1]&&v.desktopPanel_.placement.dragHand(),"Desktop border must grab");
        const auto old=v.desktopPanel_.placement.position();v.hands_[1].position.x+=.1F;
        v.desktopPanel_.placement.update(v.hands_);
        requireLive(v.desktopPanel_.placement.position().x>old.x+.09F,"Desktop grip did not move panel");
        v.hands_[1].pressed=false;v.desktopPanel_.placement.update(v.hands_);
        for(size_t h=0;h<2;++h) {
            v.hands_[h].valid=v.hands_[h].pressed=true;v.hands_[h].orientation=glm::quat(1,0,0,0);
            v.hands_[h].position=v.desktopPanel_.placement.worldPoint({h?frame.maximum.x:frame.minimum.x,0,0})+glm::vec3(0,0,.12F);
        }
        grips={};v.desktopPanel_.grips(nadoc_vr::MenuPlacement::borderContacts(v.hands_,{.025F,.025F}),{true,true},grips,[](size_t,float){});
        const auto oldScale=v.desktopPanel_.placement.scale();
        v.hands_[0].position.x-=.1F;v.hands_[1].position.x+=.1F;v.desktopPanel_.placement.update(v.hands_);
        requireLive(v.desktopPanel_.placement.scale()>oldScale,"Two border grips must resize desktop");
        v.hands_[0].pressed=v.hands_[1].pressed=false;v.desktopPanel_.placement.update(v.hands_);
        v.hands_[1].position=v.desktopPanel_.placement.worldPoint({(c.minimum.x+c.maximum.x)*.5F,(c.minimum.y+c.maximum.y)*.5F,0})+glm::vec3(0,0,.4F);
        requireLive(!v.desktopPanel_.uv(v.hands_[1]),"Close must not map to an OS click");
        v.triggerClicked_[1]=true;v.processDesktopInput({});
        requireLive(!v.desktopPanel_.open&&left.open,"Closing desktop must preserve hand menu");
        requireLive(!v.exitRequested_,"View desktop requested VR exit");
        left.open=true;activate("vr-exit");
        requireLive(v.exitRequested_&&!v.exitLoop_,"Exit VR must request normal session shutdown");
        v.latticeOpen_=v.viewTools_.open=v.desktopPanel_.open=true;
        v.sidebarMenus_.menus[1].open=true;
        const auto panels=v.remotePanelTargets();
        for(auto* placement:{&left.placement,&v.sidebarMenus_.menus[1].placement,
                &v.latticePlacement_,&v.viewTools_.placement,&v.desktopPanel_.placement})
            requireLive(std::any_of(panels.begin(),panels.end(),[&](auto p){return p.placement==placement;}),
                "A VR window was omitted from shared remote border handling");
    }
    static void verifyDashboardFocusLoss() {
        Viewer v(SceneData{}); // ordinary physical mode, no live control socket
        v.sessionState_=XR_SESSION_STATE_VISIBLE;
        v.hands_[1].valid=v.hands_[1].pressed=true;
        v.hands_[1].position={.2F,1.2F,-.5F};
        v.manipulator_.update(v.hands_);
        const auto model=v.manipulator_.transform();
        v.triggerPressed_[1]=v.triggerPartial_[1]=v.gripPressed_[1]=true;
        v.triggerValues_[1]=1;
        v.endResize_.hand=1;v.endResize_.delta=8;
        v.ligation_.hand=1;
        v.quiver_.armed[1]=true;
        v.viewTools_.placement.openDocked(v.hands_[1].position,glm::quat(1,0,0,0));
        const auto half=VRViewTools::frameHalf;
        v.hands_[1].position=v.viewTools_.placement.worldPoint({half,0,0});
        requireLive(v.viewTools_.placement.beginDrag(1,v.hands_,{-half,-half},{half,half}),"view panel grab setup failed");
        const auto panel=v.viewTools_.placement.position();
        v.syncActions(1); // unfocused path must not call OpenXR or commit edits
        requireLive(!v.hands_[1].valid&&!v.triggerPressed_[1]&&!v.gripPressed_[1]&&v.triggerValues_[1]==0,"dashboard retained held physical input");
        requireLive(v.inputResumeBlocked_[1],"dashboard return did not require button release");
        requireLive(v.manipulator_.mode()==nadoc_vr::ManipulationMode::none && v.manipulator_.transform()==model,"dashboard moved the scene");
        requireLive(!v.viewTools_.placement.dragHand() && v.viewTools_.placement.position()==panel,"dashboard retained panel grab or moved panel");
        requireLive(!v.endResize_.hand && v.endResize_.delta==0 && v.endResize_.sequence==0 && !v.ligation_.hand && !v.quiver_.armed[1],"dashboard left an edit gesture latched");
    }
    static void verifyFirstStyleAcknowledgement() {
        SceneData data;
        data.available.fill(false);
        data.available[static_cast<size_t>(Representation::full)]=true;
        data.available[static_cast<size_t>(Representation::cylinders)]=true;
        ColorSet colors;colors.values.fill({1,0,0});
        data.representations[static_cast<size_t>(Representation::full)].points.push_back(
            {"base",{0,0,-1},colors,.1F});
        data.representations[static_cast<size_t>(Representation::cylinders)].cylinders.push_back(
            {"helix",{0,-.4F,-1},{0,.4F,-1},.15F,colors});
        char directory[]="/tmp/nadoc-first-style-XXXXXX";
        requireLive(::mkdtemp(directory)!=nullptr,"temporary style directory");
        const auto path=std::filesystem::path(directory)/"visualization.txt";
        for(size_t i=0;i<kRepresentationCount;++i) {
            data.available[i]=true;
            data.representations[i].points.push_back({"base",{0,0,-1},colors,.1F});
        }
        try {
          for(size_t i=0;i<kRepresentationCount;++i) {
            const auto rep=static_cast<Representation>(i);
            Viewer viewer(data);
            viewer.glScene_=std::make_unique<GlScene>(data,true);
            viewer.visualizationPath_=path.string();
            auto& loading=viewer.representationLoading_;
            loading.enabled=true;loading.pending=true;loading.target=rep;
            loading.color=Coloring::strand;loading.phase="waiting";loading.percent=99;
            {std::ofstream out(path);out<<"NADOCVR_VISUALIZATION 3 2 none "<<representationName(rep)<<" strand 0\n";}
            viewer.pollVisualizationSnapshot();
            viewer.pollRepresentationLoading();
            requireLive(glGetError()==GL_NO_ERROR,representationName(rep));
            requireLive(viewer.glScene_->representation()==rep,
                        "first desktop acknowledgement was ignored");
            requireLive(viewer.visualizationSequence_==2 && !loading.pending && loading.percent==100,
                        "acknowledged representation load stayed at 99 percent");
          }
        } catch(...) {std::filesystem::remove_all(directory);throw;}
        std::filesystem::remove_all(directory);
    }
    static void verifySidebarHoverRay() {
        SceneData scene; scene.available[static_cast<size_t>(Representation::full)]=true;
        ColorSet colors;colors.values.fill({1,0,0});
        scene.representations[static_cast<size_t>(Representation::full)].points.push_back({"base",{0,0,-1},colors,.1F});
        Viewer viewer(scene);
        viewer.glScene_=std::make_unique<GlScene>(std::move(scene),true);
        viewer.sidebarMenus_.initialize();
        viewer.hands_[1].valid=true;
        viewer.hands_[1].position={0,0,0};
        viewer.hands_[1].orientation=glm::quat(1,0,0,0);
        auto& menu=viewer.sidebarMenus_.menus[0];
        menu.open=true;
        menu.placement.openDocked({0,0,-1},glm::quat(1,0,0,0));
        viewer.updateControllerGuides();
        auto longest=[&]() {
            float length=0;
            for(size_t i=0;i+1<viewer.controllerGuides_.size();i+=2)
                length=std::max(length,glm::length(viewer.controllerGuides_[i+1].position-viewer.controllerGuides_[i].position));
            return length;
        };
        requireLive(longest()>.5F,"unpressed controller lacks sidebar hover ray");
        menu.open=false;viewer.updateControllerGuides();
        requireLive(glGetError()==GL_NO_ERROR,"hover ray GL error");
        requireLive(longest()<.5F,"closed sidebar retains hover ray");
    }
    static void verifyOverlayMask() {
        Viewer viewer(SceneData{});
        viewer.liveCapturePending_ = 1;
        glEnable(GL_SCISSOR_TEST); glScissor(62,62,5,5);
        glClearStencil(3); glStencilMask(0xff); glClear(GL_STENCIL_BUFFER_BIT);
        glDisable(GL_SCISSOR_TEST);
        viewer.captureLiveEye(0, XrView{XR_TYPE_VIEW}, 128,128);
        requireLive(viewer.liveCapturePending_.has_value(), "ID capture failed");
        requireLive(viewer.liveEyes_[0].objectIds[64*128+64] == 0,
                    "overlay-covered object leaked through ID readback");
        requireLive(viewer.liveEyes_[0].objectIds[64*128+58] != 0,
                    "overlay mask erased uncovered object");
    }
    static void setup(Viewer& viewer, const std::string& socket) {
        viewer.liveSocket_.open(socket);
        viewer.liveSession_ = "123-456";
        viewer.liveMode_ = "control";
        viewer.liveDirectory_ = std::filesystem::path(socket).parent_path();
        viewer.sessionState_ = XR_SESSION_STATE_FOCUSED;
        viewer.selectedIdentity_ = "end:test";
        viewer.selectedSelectionKind_ = "end";
        viewer.selectedOwnerTokens_ = {"end-test"};
    }
    static std::string command(Viewer& v, const std::string& command) {
        return v.liveCommand(v.liveSession_ + " " + std::to_string(v.liveCommandSequence_ + 1) + " " + command);
    }
    static void frame(Viewer& v) {
        ++v.liveFrame_;
        if (std::chrono::steady_clock::now() > v.liveInputDeadline_) v.neutralLiveInput(false);
        for (size_t h = 0; h < 2; ++h) {
            v.hands_[h] = v.liveInput_.hands[h];
            v.triggerClicked_[h] = !v.triggerPressed_[h] && v.liveInput_.triggerPressed[h];
            v.triggerPressed_[h] = v.liveInput_.triggerPressed[h];
        }
        auto blocked = v.processThumbwheelInput({});
        v.processLatticeInput(blocked);
    }
    static void serve(Viewer& v) {
        v.liveSession_ = std::to_string(::getpid()) + "-" + std::to_string(
            std::chrono::steady_clock::now().time_since_epoch().count());
        for (;;) {
            v.pollLive();
            frame(v);
            std::this_thread::sleep_for(std::chrono::milliseconds(2));
        }
    }
    static void checks(Viewer& v) {
        v.extrudePanel_.enter(v.sidebarMenus_.menus);
        v.activateSidebarAction("feedback:activate",1);
        requireLive(v.extrudePanel_.active,"menu feedback closed Extrude controls");
        v.latticeOpen_=true;
        v.activateSidebarAction("extrude:cancel",1);
        requireLive(!v.extrudePanel_.active && !v.latticeOpen_ && !v.toolConfig_.active(),
                    "Cancel left an inactive Extrude panel or painter open");
        v.extrudePanel_.enter(v.sidebarMenus_.menus);v.latticeOpen_=true;
        v.cancelExtrudeInterface();
        requireLive(!v.extrudePanel_.active && !v.latticeOpen_,"lattice Exit left stale Extrude controls");
        nadoc_vr::ControllerPaths paths;
        const auto fixture = v.liveDirectory_ / "controller-path-test.txt";
        { std::ofstream out(fixture); out << "0 0 0 0\n0 .1 0 0\n"; }
        paths.load(fixture.string());
        requireLive(paths.generation() == 1,"path generation missing");
        { std::ofstream out(fixture); out << "0 0 0 0\n0 .2 0 0\n"; }
        paths.load(fixture.string());
        requireLive(paths.generation() == 2,"path reload not observable");
        { std::ofstream out(fixture); out << "0 0 0 0\n0 90 0 0\n"; }
        bool invalidPath = false;
        try { paths.load(fixture.string()); } catch (...) { invalidPath = true; }
        requireLive(invalidPath && paths.generation() == 2,"invalid route replaced valid path");
        std::filesystem::remove(fixture);
        std::array<nadoc_vr::HandPose,2> hands{};
        hands[0].valid = true; hands[0].position = {0,0,0}; paths.sample(hands);
        hands[0].position = {.01F,.01F,0}; paths.sample(hands);
        size_t actualLines = 0, intendedLines = 0;
        auto countPaths = [&](const auto&,const auto&,const glm::vec3& color) {
            if (color.y == 1.F) ++actualLines; else ++intendedLines;
        };
        paths.draw(countPaths);
        requireLive(actualLines == 1 && intendedLines > 1,"planned dashes/actual trace missing");
        hands[0].valid = false; paths.sample(hands); actualLines = intendedLines = 0;
        paths.draw(countPaths); requireLive(actualLines == 1,"release erased completed trace");
        hands[0].valid = true; hands[0].position = {1,0,0}; paths.sample(hands);
        actualLines = intendedLines = 0; paths.draw(countPaths);
        requireLive(actualLines == 0,"trace bridged tracking loss");

        hands[0].position={0,0,.18F}; hands[0].orientation=glm::quat(1,0,0,0);
        paths.sample(hands,glm::vec3(0),glm::vec3(0,0,1));
        hands[0].position={.02F,0,.18F};paths.sample(hands,glm::vec3(0),glm::vec3(0,0,1));
        size_t contacts=0;
        paths.drawContact([&](auto a,auto b,auto,bool actual) {
            if(actual) {++contacts;requireLive(std::abs(a.z)<1e-6F&&std::abs(b.z)<1e-6F,"contact trail stayed at controller body");}
        });
        requireLive(contacts==1,"missing contact trace");
        hands[0].valid=false;paths.sample(hands,glm::vec3(0),glm::vec3(0,0,1));contacts=0;
        paths.drawContact([&](auto,auto,auto,bool actual){contacts+=actual;});
        requireLive(contacts==1,"release erased panel contact trace");

        const auto initial = v.liveCommand("observe");
        requireLive(initial.find("\"presentation\":{\"model_to_tracking_rows\":") != std::string::npos, "missing read-only presentation mapping");
        requireLive(initial.find("\"runtime_connected\":false") != std::string::npos, "must label headless evidence");
        requireLive(v.liveCommand("old 1 button 1 trigger 1").find("stale_session") != std::string::npos, "old session accepted");
        v.liveMode_ = "inspect";
        requireLive(command(v, "pose 1 0 1 -0.3 0 0 0 1").find("read_only") != std::string::npos, "inspect mutated input");
        v.liveMode_ = "control";
        bool rejected = false;
        try { command(v, "pose 1 0 1 -0.3 0 0 0 0"); } catch (...) { rejected = true; }
        requireLive(rejected && v.liveCommandSequence_ == 0, "invalid quaternion advanced sequence");
        command(v, "pose 1 0 1 -0.3 0 0 0 1");
        requireLive(v.liveCommand("123-456 1 button 1 trigger 1").find("stale_session") != std::string::npos, "duplicate accepted");
        command(v, "activate extrude");
        requireLive(v.latticeOpen_ && v.toolConfig_.active(), "Extrude panels not opened");
        for(bool square:{false,true}) {
            v.latticeSquare_=square;
            const int step=square?8:7;
            v.activateSidebarAction("extrude:more",1);
            requireLive(v.toolConfig_.lengthBp()==step,"wrong fine lattice step");
            v.activateSidebarAction("extrude:more-period",1);
            requireLive(v.toolConfig_.lengthBp()==4*step,"wrong coarse lattice step");
            v.activateSidebarAction("extrude:less-period",1);
            requireLive(v.toolConfig_.lengthBp()==step,"wrong coarse decrement");
            v.activateSidebarAction("extrude:less",1);
            requireLive(v.toolConfig_.lengthBp()==0,"wrong fine decrement");
            v.activateSidebarAction("extrude:less-period",1);
            requireLive(v.toolConfig_.lengthBp()==0,"negative extrusion length");
        }
        v.latticeSquare_=false;
        requireLive(v.thumbwheelAvailable(),"Extrude sidebar did not expose its wheels");
        auto wheel=v.liveTargets();
        auto wheelEntry=std::find_if(wheel.begin(),wheel.end(),[](const auto& e){return e.label=="EXTRUDE LENGTH WHEEL";});
        requireLive(wheelEntry!=wheel.end(),"coarse wheel compatibility locator undiscoverable");
        auto& sidebar=v.sidebarMenus_.menus[1];
        sidebar.placement.openDocked({0,0,-1},glm::quat(1,0,0,0));
        v.latticePlacement_.openDocked({.75F,0,-1},glm::quat(1,0,0,0));
        // Put the controller in front of the lattice, then use the live semantic
        // locator. The separate production hit test must find the requested cell.
        const auto cells = v.visibleLatticeCells();
        requireLive(!cells.empty(), "lattice has no visible cells");
        const nadoc_vr::LatticeCell origin = v.latticeOrigin_;
        const auto p = v.latticePlacement_.worldPoint({0,0,0.4F});
        std::ostringstream pose;
        pose << "pose 1 " << p.x << ' ' << p.y << ' ' << p.z << " 0 0 0 1";
        command(v, pose.str());
        const auto aim = "aim_lattice 1 " + std::to_string(origin.row) + " " + std::to_string(origin.column);
        command(v, aim); frame(v);
        requireLive(v.latticeHover_ == origin, "semantic target disagrees with real lattice hit test");
        command(v, "button 1 trigger 1"); frame(v);
        requireLive(v.extrudeLatticeDraft_.cells().size() == 1, "paint failed");
        frame(v); frame(v);
        requireLive(v.extrudeLatticeDraft_.cells().size() == 1, "held paint toggled repeatedly");
        command(v, "button 1 trigger 0"); frame(v);
        command(v, "button 1 trigger 1"); frame(v);
        requireLive(v.extrudeLatticeDraft_.cells().empty(), "second stroke did not erase");
        command(v, "button 1 trigger 0"); frame(v);
        command(v, "button 1 trigger 1"); frame(v);
        requireLive(v.liveCommand("observe").find("\"commit_supported\":false") != std::string::npos, "unresolved footprint advertised as committed");
        command(v, "button 1 trigger 0"); frame(v);
        // Exercise the real thumbwheel ray and detent handler, with lattice input
        // blocked while the wheel owns the trigger.
        auto setAt = [&](const glm::vec3& position, const glm::quat& orientation, size_t hand=1) {
            std::ostringstream text;
            text << "pose " << hand << ' ' << position.x << ' ' << position.y << ' ' << position.z << ' '
                 << orientation.x << ' ' << orientation.y << ' ' << orientation.z << ' ' << orientation.w;
            command(v, text.str());
        };
        sidebar.placement.openDocked({0,0,-1},glm::angleAxis(.25F,glm::vec3(0,1,0)));
        sidebar.placement.setScale(.6F);
        for(size_t index=0;index<2;++index) {
            const auto front=nadoc_vr::extrudeWheelFront(index);
            setAt(sidebar.placement.worldPoint(front+glm::vec3(0,0,.4F)),sidebar.placement.orientation());
            command(v,index==0?"aim 1 EXTRUDE LENGTH WHEEL":"aim 1 RIGHT / FINE [extrude:fine-wheel]");frame(v);
            requireLive(v.thumbwheelHovered_==index,"wheel locator misses production sidebar hit test");
            const auto targets=v.liveTargets();
            const auto target=std::find_if(targets.begin(),targets.end(),[&](const auto& entry){
                return entry.id==nadoc_vr::kExtrudeWheelIds[index];
            });
            requireLive(target!=targets.end() && glm::length(target->hitHalfRight)>0 &&
                        glm::length(target->hitHalfUp)>0 &&
                        glm::distance(target->worldPosition,sidebar.placement.worldPoint(front))<1e-5F,
                        "wheel pose or hit rectangle telemetry disagrees with sidebar");
            const auto wheelOrientation=v.liveInput_.hands[1].orientation;
            const int beforeLength=v.toolConfig_.lengthBp();
            const auto beforeCells=v.extrudeLatticeDraft_.cells();
            command(v,"button 1 trigger 1");frame(v);
            requireLive(v.thumbwheelHand_==1 && v.thumbwheelControls_[index].dragging(),"wheel did not acquire trigger");
            const auto telemetry=std::string("\"id\":\"")+nadoc_vr::kExtrudeWheelIds[index]+
                "\",\"label\":\""+(index==0?"coarse":"fine")+
                "\",\"available\":true,\"hovered\":true,\"dragging\":true";
            requireLive(v.liveState().find(telemetry)!=std::string::npos,"active wheel runtime state missing");
            // The other controller cannot steal the shared wheel gesture.
            setAt(sidebar.placement.worldPoint(nadoc_vr::extrudeWheelFront(1-index)+glm::vec3(0,0,.4F)),sidebar.placement.orientation(),0);
            command(v,"button 0 trigger 1");frame(v);
            requireLive(v.thumbwheelHand_==1 && !v.thumbwheelControls_[1-index].dragging(),"second hand stole wheel ownership");
            command(v,"button 0 trigger 0");frame(v);
            setAt(sidebar.placement.worldPoint(front+glm::vec3(0,index==0?.125F:.045F,.4F)),wheelOrientation);
            frame(v);
            requireLive(v.toolConfig_.lengthBp()==beforeLength+(index==0?21:1),"coarse/fine wheel detents incorrect");
            requireLive(v.extrudeLatticeDraft_.cells()==beforeCells,"wheel trigger painted lattice");
            for(int i=0;i<12;++i)frame(v); // stop motion before release
            command(v,"button 1 trigger 0");frame(v);
            requireLive(!v.thumbwheelHand_ && !v.thumbwheelControls_[index].moving(),"slow release retained wheel ownership or inertia");
        }
        // Grip panel movement uses the same production placement object.
        const auto bounds = sidebar.bounds();
        const auto border = sidebar.placement.worldPoint({bounds.maximum.x, 0, 0});
        setAt(border, sidebar.placement.orientation()); frame(v);
        v.hands_[1].pressed = true;
        requireLive(sidebar.placement.beginDrag(1, v.hands_, bounds.minimum, bounds.maximum), "border grip missed");
        const auto beforePanel = sidebar.placement.position();
        v.hands_[1].position.x += 0.2F;
        sidebar.placement.update(v.hands_, nadoc_vr::MenuPlacement::kMenuHalfWidth);
        requireLive(std::abs(sidebar.placement.position().x - beforePanel.x - 0.2F) < 1e-5F, "panel drag displacement incorrect");
        command(v, "release"); frame(v);
        requireLive(!v.triggerPressed_[1] && !v.liveInput_.hands[1].valid, "release left held input");
        v.cancelExtrudeInterface();
        requireLive(!v.latticeOpen_ && v.extrudeLatticeDraft_.cells().empty(), "cancel retained draft");
        v.sessionState_ = XR_SESSION_STATE_VISIBLE;
        requireLive(command(v, "button 1 trigger 1").find("not_focused") != std::string::npos, "unfocused command accepted");
        requireLive(command(v, "release").find("\"error\"") == std::string::npos, "unfocused release refused");
        v.liveMode_ = "inspect";
        const float scaleBefore = v.normalizationScale_;
        command(v, "scene_visibility hidden");
        requireLive(v.liveSceneHidden_ && v.normalizationScale_ == scaleBefore,"visibility changed model scale");
        requireLive(v.liveState().find("\"scene_visibility\":\"hidden\"") != std::string::npos,"visibility not disclosed");
        command(v, "scene_visibility normal");
        requireLive(!v.liveSceneHidden_,"scene visibility did not restore");
    }
};
}

// Real framebuffer check: recoloring must preserve the directional lighting
// ratio, and surfaces must receive the shared shadow sampler. No headset needed.
void verifyTabletLighting(GLuint fbo) {
    VRViewTools t;t.initialize();t.version=1;
    auto sample=[&](glm::vec4 color,bool shadow) {
        t.triangles.clear();
        for(int side=0;side<2;++side){const float x=side?0.F:-1.F;
            const glm::vec3 n=side?glm::vec3(1,0,0):glm::vec3(0,0,1);
            for(auto p:std::array<glm::vec3,6>{{{x,-1,0},{x+1,-1,0},{x,1,0},{x,1,0},{x+1,-1,0},{x+1,1,0}}})t.triangles.push_back({p,color,{-1,-1},n});
        }
        glBindBuffer(GL_ARRAY_BUFFER,t.triangleVbo);glBufferData(GL_ARRAY_BUFFER,t.triangles.size()*sizeof(VRViewTools::V),t.triangles.data(),GL_STATIC_DRAW);
        glBindFramebuffer(GL_FRAMEBUFFER,fbo);glViewport(0,0,128,128);
        glDrawBuffer(GL_COLOR_ATTACHMENT0);glClearColor(0,0,0,1);glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT);
        glUseProgram(t.program);glUniform3f(glGetUniformLocation(t.program,"uLightDirection"),0,0,1);
        const glm::mat4 identity(1);glUniformMatrix4fv(glGetUniformLocation(t.program,"uLightViewProjection"),1,GL_FALSE,&identity[0][0]);
        glUniform1i(glGetUniformLocation(t.program,"uShadowsEnabled"),shadow);glUniform1i(glGetUniformLocation(t.program,"uShadowMap"),0);
        t.renderScene(identity,identity,{1,0,0,0});
        std::array<unsigned char,4> a{},b{};glReadBuffer(GL_COLOR_ATTACHMENT0);
        glReadPixels(32,64,1,1,GL_RGBA,GL_UNSIGNED_BYTE,a.data());glReadPixels(96,64,1,1,GL_RGBA,GL_UNSIGNED_BYTE,b.data());
        return std::array{a,b};
    };
    const auto gray=sample({.25F,.25F,.25F,1},false);
    const auto recolored=sample({.08F,.25F,.04F,1},false);
    requireLive(gray[0][0]>gray[1][0]*4 && gray[1][0]>10,"View overlay surfaces lost directional shading");
    requireLive(std::abs(int(gray[0][1])-int(recolored[0][1]))<=1 && std::abs(int(gray[1][1])-int(recolored[1][1]))<=1,
                "Recoloring changed unchanged-channel lighting");
    GLuint depth;glGenTextures(1,&depth);glActiveTexture(GL_TEXTURE0);glBindTexture(GL_TEXTURE_2D,depth);
    const float blocker=.1F;glTexImage2D(GL_TEXTURE_2D,0,GL_DEPTH_COMPONENT24,1,1,0,GL_DEPTH_COMPONENT,GL_FLOAT,&blocker);
    glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_NEAREST);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_COMPARE_MODE,GL_COMPARE_REF_TO_TEXTURE);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_COMPARE_FUNC,GL_LEQUAL);
    const auto shaded=sample({.25F,.25F,.25F,1},true);
    requireLive(shaded[0][0]<gray[0][0]/3 && std::abs(int(shaded[0][0])-int(gray[1][0]))<=2,"View overlay ignored shared shadows");
    glDeleteTextures(1,&depth);t.shutdown();
}

// Real rasterization regression: nearest sphere wins regardless of draw order,
// discarded impostor corners stay zero, all primitive shaders write IDs, and
// IDs survive representation changes. No OpenXR runtime is required.
int objectIdGlChecks(bool tabletOnly=false) {
    if (!glfwInit()) return 77;
    glfwWindowHint(GLFW_VISIBLE, GLFW_FALSE);
    glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR, 3);
    glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR, 3);
    glfwWindowHint(GLFW_OPENGL_PROFILE, GLFW_OPENGL_CORE_PROFILE);
    GLFWwindow* window = glfwCreateWindow(128, 128, "ScryWrite ID test", nullptr, nullptr);
    if (!window) { glfwTerminate(); return 77; }
    glfwMakeContextCurrent(window);
    GLuint fbo, color, ids, depth;
    glGenFramebuffers(1, &fbo); glBindFramebuffer(GL_FRAMEBUFFER, fbo);
    glGenTextures(1, &color); glBindTexture(GL_TEXTURE_2D, color);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, 128,128,0,GL_RGBA,GL_UNSIGNED_BYTE,nullptr);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, color,0);
    glGenTextures(1, &ids); glBindTexture(GL_TEXTURE_2D, ids);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_R32UI,128,128,0,GL_RED_INTEGER,GL_UNSIGNED_INT,nullptr);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT1, GL_TEXTURE_2D,ids,0);
    glGenRenderbuffers(1, &depth); glBindRenderbuffer(GL_RENDERBUFFER,depth);
    glRenderbufferStorage(GL_RENDERBUFFER,GL_DEPTH24_STENCIL8,128,128);
    glFramebufferRenderbuffer(GL_FRAMEBUFFER,GL_DEPTH_STENCIL_ATTACHMENT,GL_RENDERBUFFER,depth);
    requireLive(glCheckFramebufferStatus(GL_FRAMEBUFFER)==GL_FRAMEBUFFER_COMPLETE,"ID test framebuffer");
    verifyTabletLighting(fbo);
    if(tabletOnly){
        glDeleteTextures(1,&color);glDeleteTextures(1,&ids);glDeleteRenderbuffers(1,&depth);glDeleteFramebuffers(1,&fbo);
        glfwDestroyWindow(window);glfwTerminate();std::cout << "View tablet recolor lighting and shadows passed.\n";return 0;
    }
    verifyRepresentationShadows(fbo);
    verifySphereProjectionLighting(fbo);
    LiveViewerTest::verifyFirstStyleAcknowledgement();
    LiveViewerTest::verifySidebarHoverRay();
    SceneData data;
    data.available.fill(true); // Programmatic fixture; file loading normally derives this.
    ColorSet colors; colors.values.fill({1,0,0});
    auto& full=data.representations[static_cast<size_t>(Representation::full)];
    full.points={{"front",{0,0,-1},colors,.2F},{"rear",{0,0,-2},colors,.4F}};
    full.points[0].vdwSize=.3F;
    full.ownerAliases.push_back({"front", {"canonical-front"}});
    full.cylinders.push_back({"cylinder",{-.6F,-.4F,-1},{-.6F,.4F,-1},.07F,colors});
    full.halfCylinders.push_back({"half",{.5F,-.4F,-1},{.5F,.4F,-1},.1F,colors});
    full.boxes.push_back({"box",{0,.6F,-1},{.12F,0,0},{0,.1F,0},{0,0,.08F},colors});
    for(auto& point:full.points)point.colors.values[1]={0,1,0};
    auto& stick=data.representations[static_cast<size_t>(Representation::stick)];
    stick.cylinders=full.cylinders;
    data.representations[static_cast<size_t>(Representation::ballstick)]=full;
    auto& surface=data.representations[static_cast<size_t>(Representation::surface)];
    surface.boxes.push_back({"triangle",{0,0,-1},{.8F,0,0},{0,.8F,0},{0,0,.00001F},colors,
        {glm::vec3(0,0,1),glm::vec3(0,0,1),glm::vec3(0,0,1)}});
    data.representations[static_cast<size_t>(Representation::oxdna)].boxes.push_back(
        {"ellipsoid",{0,0,-1},{.8F,0,0},{0,.4F,0},{0,0,.4F},colors});
    {
        SceneData partial;
        partial.available[static_cast<size_t>(Representation::surface)]=true;
        partial.representations[static_cast<size_t>(Representation::surface)]=data.representations[static_cast<size_t>(Representation::surface)];
        partial.representations[static_cast<size_t>(Representation::full)].cylinders.push_back(
            {"viewer:axis",{10,10,-1},{11,10,-1},.01F,colors});
        GlScene scene(std::move(data),true);
        scene.installRepresentation(std::move(partial));
        scene.setStyle(Representation::full,Coloring::strand);
        std::vector<nadoc_vr::ViewVolumeRecord> volumes;
        bool volumeMode=false,lightweight=false;
        auto render = [&]() {
            glBindFramebuffer(GL_FRAMEBUFFER,fbo); glViewport(0,0,128,128);
            const GLenum buffers[]={GL_COLOR_ATTACHMENT0,GL_COLOR_ATTACHMENT1};
            glDrawBuffers(2,buffers); const GLuint zero[]={0,0,0,0};
            glClearBufferuiv(GL_COLOR,1,zero); glDrawBuffer(GL_COLOR_ATTACHMENT0);
            glClearStencil(1); glStencilMask(0xff);
            glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT|GL_STENCIL_BUFFER_BIT);
            glEnable(GL_DEPTH_TEST); glDepthFunc(GL_LESS);
            if(volumeMode) scene.renderVolumes(glm::perspective(glm::radians(90.0F),1.0F,.05F,10.0F),glm::mat4(1),{},true,volumes,lightweight);
            else scene.render(glm::perspective(glm::radians(90.0F),1.0F,.05F,10.0F),glm::mat4(1),{},true,lightweight);
            std::vector<uint32_t> pixels(128*128);
            glReadBuffer(GL_COLOR_ATTACHMENT1);
            glReadPixels(0,0,128,128,GL_RED_INTEGER,GL_UNSIGNED_INT,pixels.data());
            glReadBuffer(GL_COLOR_ATTACHMENT0);
            requireLive(glGetError()==GL_NO_ERROR,"OpenGL ID error");
            return pixels;
        };
        auto pixels=render();
        uint32_t front=pixels[64*128+64];
        requireLive(front!=0,"front sphere missing ID");
        requireLive(scene.objectTable({front}).find("canonical-front")!=std::string::npos,"ID owner table mismatch");
        requireLive(pixels[76*128+76]==0,"discarded sphere corner wrote ID");
        std::vector<uint32_t> unique=pixels;
        std::sort(unique.begin(),unique.end());unique.erase(std::unique(unique.begin(),unique.end()),unique.end());
        auto table=scene.objectTable(unique);
        for (const char* name : {"front","cylinder","half","box"}) requireLive(table.find(name)!=std::string::npos,"primitive ID missing");
        requireLive(table.find("rear")==std::string::npos,"occluded rear object leaked");
        lightweight=true;
        auto points=render();
        requireLive(points[64*128+64]==front,"loading point lost visible identity");
        auto pointIds=points;std::sort(pointIds.begin(),pointIds.end());pointIds.erase(std::unique(pointIds.begin(),pointIds.end()),pointIds.end());
        const auto pointTable=scene.objectTable(pointIds);
        for(const char* name:{"front","cylinder","half","box"})
            requireLive(pointTable.find(name)!=std::string::npos,"loading fallback omitted primitive family");
        requireLive(pointTable.find("rear")==std::string::npos,"loading fallback lost depth occlusion");
        requireLive(scene.pick({{0,0,0},{0,0,-1}},glm::mat4(1)).has_value(),"loading fallback lost picking");
        lightweight=false;requireLive(render()==pixels,"loading fallback changed resident geometry");
        // The right half of the sphere changes style; the left half stays red.
        nadoc_vr::ViewVolumeRecord volume;volume.enabled=true;volume.editable=true;
        volume.center={.5F,0,kViewDistanceMeters-1};volume.half={.5F,1,1};
        volume.representation="beads";volume.coloring="base";volumes={volume};volumeMode=true;
        render();
        auto rgb=[&](int x,int y){std::array<unsigned char,4> p{};glReadPixels(x,y,1,1,GL_RGBA,GL_UNSIGNED_BYTE,p.data());return p;};
        auto left=rgb(59,64),right=rgb(69,64);
        requireLive(left[0]>left[1] && right[1]>right[0],"local volume did not replace only the inside style");
        volumes[0].enabled=false;render();right=rgb(69,64);
        requireLive(right[0]>right[1],"disabled volume still changed representation");
        volumes.clear();requireLive(render()==pixels,"volume rendering changed unmasked object IDs");
        volumeMode=false;
        scene.setSelectionHighlights({}, {}, {}, {"front"});
        requireLive(render()==pixels,"decorative glow changed object IDs");
        LiveViewerTest::verifyOverlayMask();
        scene.setSelectionHighlights({}, {}, {}, {});
        scene.setStyle(Representation::stick,Coloring::strand);
        pixels=render();unique=pixels;std::sort(unique.begin(),unique.end());unique.erase(std::unique(unique.begin(),unique.end()),unique.end());
        requireLive(scene.objectTable(unique).find("cylinder")!=std::string::npos,"atomistic line IDs missing");
        scene.setStyle(Representation::full,Coloring::base);
        requireLive(render()[64*128+64]==front,"object ID changed after style switch");
        scene.setStyle(Representation::surface,Coloring::strand);
        requireLive(!scene.pick({{.3F,.3F,0},{0,0,-1}},glm::mat4(1)),"invisible triangle corner remained selectable");
        requireLive(scene.pick({{-.1F,-.1F,0},{0,0,-1}},glm::mat4(1)).has_value(),"triangle ray target missing");
        auto triangles=render();
        requireLive(triangles[60*128+60]!=0 && triangles[76*128+76]==0,"triangle shape or IDs incorrect");
        scene.setStyle(Representation::oxdna,Coloring::strand);
        requireLive(!scene.pick({{.38F,.18F,0},{0,0,-1}},glm::mat4(1)),"ellipsoid bounding-box corner remained selectable");
        auto ellipsoids=render();
        requireLive(ellipsoids[64*128+64]!=0 && ellipsoids[78*128+78]==0,"ellipsoid shape or IDs incorrect");
        scene.setStyle(Representation::vdw,Coloring::strand);
        requireLive(scene.pick({{.25F,0,0},{0,0,-1}},glm::mat4(1)).has_value(),"VDW uses smaller ballstick picking radius");
        requireLive(!scene.pick({{-.6F,0,0},{0,0,-1}},glm::mat4(1)),"invisible VDW bonds remained selectable");
        glClearStencil(0); glClear(GL_STENCIL_BUFFER_BIT);
        glEnable(GL_STENCIL_TEST); glStencilOp(GL_KEEP, GL_KEEP, GL_REPLACE);
        std::vector<Vertex> guides{
            {{-.8F,-.5F,0},{1,0,0},1}, {{-.2F,-.5F,0},{1,0,0},1},
            {{.2F,.5F,0},{0,1,0},1}, {{.8F,.5F,0},{0,1,0},1}};
        const std::array<size_t,2> ends{2,4};
        scene.renderGuides(glm::mat4(1),guides,&ends);
        std::vector<uint8_t> classes(128*128);
        glReadPixels(0,0,128,128,GL_STENCIL_INDEX,GL_UNSIGNED_BYTE,classes.data());
        requireLive(std::count(classes.begin(),classes.end(),4)>10,"left controller identity missing");
        requireLive(std::count(classes.begin(),classes.end(),5)>10,"right controller identity missing");
        const auto coverage=nadoc_vr::assessSpectatorCoverage(classes);
        requireLive(coverage.overlayPixels>20 && coverage.unknownPixels==0,"controller tags broke mirror coverage");
        glEnable(GL_SCISSOR_TEST); glScissor(0,0,128,64);
        glClearStencil(3); glClear(GL_STENCIL_BUFFER_BIT); glDisable(GL_SCISSOR_TEST);
        glReadPixels(0,0,128,128,GL_STENCIL_INDEX,GL_UNSIGNED_BYTE,classes.data());
        requireLive(std::count(classes.begin(),classes.end(),4)==0,"covered controller counted visible");
        requireLive(std::count(classes.begin(),classes.end(),5)>10,"uncovered controller erased");
        glDisable(GL_STENCIL_TEST);
    }
    {
        SceneData data;data.available.fill(true);
        auto& full=data.representations[static_cast<size_t>(Representation::full)];
        full.points={{"a:backbone",{0,0,-1},colors,.1F},{"b:backbone",{2,0,-1},colors,.1F}};
        full.ownerAliases={{"a:backbone",{"a","overhang","cluster"}},
                           {"b:backbone",{"b","overhang","cluster"}}};
        full.toolHandles={{"a","a","base",{0,0,-1}},{"b","b","base",{2,0,-1}},
                          {"o","overhang","overhang",{1,0,-1}}};
        full.ownerHandles={{"cluster",{1,0,-1}}};
        data.representations[static_cast<size_t>(Representation::ballstick)]=full;
        SceneData partial;
        partial.available[static_cast<size_t>(Representation::surface)]=true;
        partial.representations[static_cast<size_t>(Representation::surface)]=data.representations[static_cast<size_t>(Representation::surface)];
        partial.representations[static_cast<size_t>(Representation::full)].cylinders.push_back(
            {"viewer:axis",{10,10,-1},{11,10,-1},.01F,colors});
        GlScene scene(std::move(data),true);
        scene.installRepresentation(std::move(partial));
        scene.setStyle(Representation::full,Coloring::strand);scene.setStyle(Representation::full,Coloring::strand);
        auto center=[&](const std::string& token,glm::vec3 expected) {
            const auto actual=scene.ownerHandle({token},glm::mat4(1));
            requireLive(actual && glm::distance(*actual,expected)<1e-5F,"cached related handle drifted");
        };
        scene.setToolPreview({"cluster"},glm::translate(glm::mat4(1),glm::vec3(1,0,0)));
        requireLive(scene.acceptToolCommit(),"cluster commit failed");
        center("a",{1,0,-1});center("overhang",{2,0,-1});
        scene.setStyle(Representation::ballstick,Coloring::strand);
        center("a",{1,0,-1});
        scene.setToolPreview({"a"},glm::translate(glm::mat4(1),glm::vec3(0,1,0)));
        requireLive(scene.acceptToolCommit(),"base commit failed");
        center("a",{1,1,-1});center("b",{3,0,-1});
        center("cluster",{2,.5F,-1});center("overhang",{2,.5F,-1});
        requireLive(scene.acceptToolUndo(),"base undo failed");
        center("a",{1,0,-1});center("cluster",{2,0,-1});
        auto turn=glm::translate(glm::mat4(1),glm::vec3(2,0,-1))
            *glm::rotate(glm::mat4(1),glm::radians(90.F),glm::vec3(0,0,1))
            *glm::translate(glm::mat4(1),glm::vec3(-2,0,1));
        scene.setToolPreview({"overhang"},turn);
        requireLive(scene.acceptToolCommit(),"overhang commit failed");
        center("a",{2,-1,-1});center("b",{2,1,-1});center("cluster",{2,0,-1});
        requireLive(scene.acceptToolUndo(),"overhang undo failed");center("a",{1,0,-1});
    }
    glDeleteTextures(1,&color); glDeleteTextures(1,&ids);
    glDeleteRenderbuffers(1,&depth); glDeleteFramebuffers(1,&fbo);
    glfwDestroyWindow(window);glfwTerminate();
    std::cout << "Real GL object identity/occlusion checks passed.\n";
    return 0;
}

int main(int argc, char** argv) {
    try {
        if (argc == 2 && std::string(argv[1]) == "--tablet-lighting") return objectIdGlChecks(true);
        if (argc == 2 && std::string(argv[1]) == "--gl-ids") return objectIdGlChecks();
        if (argc < 2) return 2;
        // IPC clients exercise production handlers directly. Keep their server
        // entry point independent of unrelated panel unit assertions below.
        if (argc == 4 && std::string(argv[2]) == "--serve") {
            Viewer viewer(loadScene(argv[1]));
            LiveViewerTest::setup(viewer, argv[3]);
            LiveViewerTest::serve(viewer);
            return 0;
        }
        if (argc == 2 && std::string(argv[1]) == "--quiver") {
            LiveViewerTest::verifyQuiverReactivation();
            LiveViewerTest::verifyViewToolsDismissal();
            std::cout << "Quiver lifecycle, independent hands and controller following and docking passed.\n";
            return 0;
        }
        if (argc == 2 && std::string(argv[1]) == "--nick-catalog") {
            LiveViewerTest::verifyNickCatalog();
            return 0;
        }
        LiveViewerTest::verifyQuiverReactivation();
        LiveViewerTest::verifyNickCatalog();
        LiveViewerTest::verifyDashboardFocusLoss();
        LiveViewerTest::verifyViewToolsFrameSeam();
        LiveViewerTest::verifyVRTabActions();
        LiveViewerTest::verifySidebarSpawnView();
        LiveViewerTest::verifyRadialHistoryAndCurrentPanels();
        LiveViewerTest::verifyTrajectoryLauncherWithBothSidebars();
        char directory[] = "/tmp/nadoc-scry-test-XXXXXX";
        if (!::mkdtemp(directory)) return 2;
        LiveViewerTest::verifyTrajectorySidebar(directory);
        const auto socket = std::string(directory) + "/viewer.sock";
        {
            Viewer viewer(loadScene(argv[1]));
            LiveViewerTest::setup(viewer, socket);
            LiveViewerTest::checks(viewer);
        }
        std::filesystem::remove_all(directory);
        std::cout << "Live viewer control/Extrude checks passed (no runtime or GL).\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n'; return 1;
    }
}
