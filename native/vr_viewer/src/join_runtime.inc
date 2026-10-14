    bool joinActionAvailable(const std::string& action) const {
        if(!movePanel_.active || !movePanel_.joining || toolShell_.executionPending() || moveAwaitRefresh_)return false;
        if(action=="join:apply")return joinReady();
        if(action=="join:snap")return false;
        if(action=="join:undo" || action=="join:redo")return !ligation_.waiting && ligation_.version>0;
        if(action.size()>5 && std::isdigit(action[5]))return moveAvailable() && !movePanel_.hand;
        return true;
    }
    bool joinReady() const {
        return movePanel_.active && movePanel_.joining && !movePanel_.moving() &&
            toolShell_.previewRequested() && joinPreview_.ready(toolSequence_,transformSequence_);
    }
    void activateJoin() {
        if(toolShell_.executionPending())return;
        if(sweepPanel_.active)cancelSweep();
        if(ligation_.active || ligation_.nickActive) {
            ligation_.setActive(false);publishSelectionLevel(ligationPreviousLevel_);
        }
        if(movePanel_.active){cancelMove();movePanel_.exit(sidebarMenus_.menus);}
        if(extrudePanel_.active)extrudePanel_.exit(sidebarMenus_.menus);
        if(volumePanel_.active)volumePanel_.exit(sidebarMenus_.menus);
        if(dimensionPanel_.tool.active)dimensionPanel_.exit(sidebarMenus_.menus);
        if(bendPanel_.active)bendPanel_.exit(sidebarMenus_.menus);
        // Sidebar dispatch may already have retired the Bend panel. Clear its
        // target-bound guides and any pending picker regardless of panel state.
        clearPlanePick();clearPlaneGuides();
        if(!sidebarMenus_.menus[1].open)toggleSidebar(1);
        radialToolMenu_.close();latticeOpen_=false;
        movePanel_.joining=true;movePanel_.snap=false;movePanel_.enter(sidebarMenus_.menus);movePanel_.selecting=true;
        joinPreview_.clear();joinFeedbackReader_.setPath(eventPath_.empty()?"":eventPath_+".join");
        toolShell_.activate(nadoc_vr::ToolMode::join,selectedSelectionKind_);
        if(toolConfig_.clear())publishToolConfiguration();
        pendingToolTransform_.cancel();publishToolTransform();
        publishToolIntent(nadoc_vr::ToolAction::activate);publishSelectionLevel("cluster");
        suppressManipulationUntilRelease_=true;
        refreshJoin();movePanel_.refresh(sidebarMenus_.menus,selectedSelectionKind_,toolShell_.status());
    }
    void refreshJoin() {
        if(!movePanel_.joining)return;
        joinPreview_.accept(joinFeedbackReader_.latest(),toolSequence_,transformSequence_);
        nadoc_vr::CalculationScope scope("joinProximityHints");
        joinPreview_.update(lastToolTransform_);
        const auto& feedback=joinPreview_.feedback;
        const std::string reason=feedback && feedback->requestSequence==transformSequence_ && (feedback->status=="failed" || feedback->status=="invalid")?feedback->message:"";
        movePanel_.connectionStatus=toolShell_.executionPending()?"JOINING / ROUTING":movePanel_.selecting?"SELECT A MOVING CLUSTER"
            :joinReady()?std::to_string(feedback->connections)+" CONNECTIONS / APPLY TO JOIN"
            :toolShell_.status()=="COMMIT FAILED" || toolShell_.status()=="COMMIT REFUSED"?"JOIN FAILED / ADJUST OR RETRY"
            :!reason.empty()?reason
            :joinPreview_.hintCount?std::to_string(joinPreview_.hintCount)+" POSSIBLE / CHECKING CONNECTIONS"
            :"MOVE CLUSTER TO FIND CONNECTIONS";
    }
    template<class Line> void drawJoin(Line line) const {
        if(!movePanel_.active || !movePanel_.joining || movePanel_.selecting)return;
        const auto point=[&](glm::vec3 p){return glm::vec3(manipulator_.transform()*glm::vec4(
            nadoc_vr::sourceToNormalizedPoint(p,normalizationCenter_,normalizationScale_,{0,0,-kViewDistanceMeters}),1));};
        if(joinPreview_.ready(toolSequence_,transformSequence_)) {
            for(const auto& segment:joinPreview_.feedback->bridges)line(point(segment.first),point(segment.second),{.3F,1.F,.65F});
        } else for(size_t i=0;i<joinPreview_.hintCount;++i) {
            const auto& s=joinPreview_.hints[i];
            // Dashes distinguish live proximity from browser-checked bridges.
            for(int n=0;n<7;n+=2)line(point(glm::mix(s.first,s.second,n/7.F)),point(glm::mix(s.first,s.second,(n+1)/7.F)),{.68F,.76F,.88F});
        }
    }
