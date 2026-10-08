// Native editor wiring. Geometry remains a draft until the browser acknowledges
// the exact configuration and commits the canonical desktop Sweep feature.
    glm::vec3 sweepDefaultDirection() const {
        return extrudePlane_.plane=="XZ"?glm::vec3(0,10,0):extrudePlane_.plane=="YZ"?glm::vec3(10,0,0):glm::vec3(0,0,10);
    }
    glm::vec3 sweepCellNm(const nadoc_vr::LatticeCell& cell) const {
        const auto p=nadoc_vr::latticeCellOffsetNanometers(cell,{},latticeSquare_);
        return extrudePlane_.plane=="XZ"?glm::vec3(p.x,0,p.y):extrudePlane_.plane=="YZ"?glm::vec3(0,p.x,p.y):glm::vec3(p,0);
    }
    glm::vec3 sweepOriginNm() const {
        glm::vec3 origin{};
        for(const auto& cell:extrudeLatticeDraft_.cells())origin+=sweepCellNm(cell);
        return origin/float(std::max(size_t(1),extrudeLatticeDraft_.cells().size()));
    }
    glm::mat4 sweepWorldTransform() const {
        return manipulator_.transform()*
            glm::translate(glm::mat4(1),glm::vec3(0,0,-kViewDistanceMeters)-normalizationCenter_*normalizationScale_)*
            glm::scale(glm::mat4(1),glm::vec3(normalizationScale_))*glm::mat4(sourceAxes_)*
            glm::translate(glm::mat4(1),sweepOriginNm());
    }
    glm::vec3 sweepWorldPoint(glm::vec3 relative) const {
        return glm::vec3(sweepWorldTransform()*glm::vec4(relative,1));
    }
    glm::vec3 sweepRelativePoint(glm::vec3 world) const {
        return glm::vec3(glm::inverse(sweepWorldTransform())*glm::vec4(world,1));
    }
    bool sweepReady() const {
        const auto* feedback=currentToolPreflightFeedback();
        return sweepPanel_.active && sweepDraft_.step==2 && sweepDraft_.validPath() && !sweepHand_ &&
            std::none_of(extrudeLatticeDraft_.cells().begin(),extrudeLatticeDraft_.cells().end(),
                [&](const auto& cell){return latticeCellOccupied(cell);}) &&
            !extrudeLatticeDraft_.cells().empty() && !eventPath_.empty() && !toolShell_.executionPending() &&
            feedback && feedback->mode=="sweep" && feedback->status=="ok" &&
            feedback->toolConfigSequence==toolConfigSequence_;
    }
    std::string sweepStatus() const {
        if(!sweepPanel_.active)return {};
        if(toolShell_.executionPending())return "BUILDING SWEEP";
        if(sweepDraft_.drawing)return "DRAWING / RELEASE TRIGGER TO FINISH";
        if(sweepDraft_.freeDrawArmed)return "HOLD RIGHT TRIGGER TO DRAW";
        if(sweepDraft_.step==1)return "STEP 1/2 / PAINT LATTICE CELLS";
        if(sweepDraft_.strokeInvalid)return "INVALID STROKE / TRY FREE DRAW AGAIN";
        if(!sweepDraft_.validPath())return "ADD A SECOND DISTINCT POINT OR FREE DRAW";
        if(eventPath_.empty())return "OPEN VR FROM YOUR DESIGN";
        if(sweepReady())return "STEP 2/2 / READY TO SWEEP";
        const auto* feedback=currentToolPreflightFeedback();
        if(feedback && (feedback->status=="error" || feedback->status=="block"))return "ADJUST PATH / "+feedback->reason;
        return "STEP 2/2 / VALIDATING PATH";
    }
    bool sweepActionAvailable(const std::string& action) const {
        if(!sweepPanel_.active || toolShell_.executionPending())return false;
        if(sweepDraft_.drawing || sweepHand_)return action=="sweep:cancel";
        if(action=="sweep:confirm")return sweepDraft_.step==1?!extrudeLatticeDraft_.cells().empty():sweepReady();
        if(action=="sweep:undo")return toolShell_.undoAvailable();
        if(action=="sweep:lattice" || action=="sweep:status")return false;
        if(action=="sweep:add-point")return !sweepDraft_.freeDrawArmed && sweepDraft_.pointsNm.size()<256;
        if(action=="sweep:delete-point")return !sweepDraft_.freeDrawArmed && sweepDraft_.selected>0 && sweepDraft_.pointsNm.size()>1;
        if(action=="sweep:delete-last-point")return !sweepDraft_.freeDrawArmed && sweepDraft_.pointsNm.size()>1;
        if(action.starts_with("sweep:axis:0:"))return false;
        return true;
    }
    void activateSweep() {
        if(toolShell_.executionPending())return;
        activateAuthoringTool(4);
        if(extrudePanel_.active)extrudePanel_.exit(sidebarMenus_.menus);
        if(!sidebarMenus_.menus[1].open)toggleSidebar(1);
        sweepDraft_.reset(sweepDefaultDirection());sweepHand_.reset();sweepHovered_={};
        sweepGeometryRevision_=std::numeric_limits<uint64_t>::max();
        sweepPanel_.enter(sidebarMenus_.menus);
        toolShell_.activate(nadoc_vr::ToolMode::sweep,"none");
        (void)toolConfig_.bind(nadoc_vr::ToolMode::sweep,"","none",{});
        publishToolIntent(nadoc_vr::ToolAction::activate);
        openExtrudeLattice();radialToolMenu_.close();refreshExtrudePanel();
    }
    void cancelSweep() {
        if(toolShell_.executionPending())return;
        sweepHand_.reset();sweepHovered_={};sweepDraft_.cancelStroke();
        sweepPanel_.exit(sidebarMenus_.menus);latticeOpen_=false;latticePaintStroke_.reset();
        latticeHover_.reset();latticeGrip_.cancel();extrudeLatticeDraft_.clear();radialToolMenu_.close();
        toolShell_.apply(nadoc_vr::ToolAction::cancel,"none");publishToolIntent(nadoc_vr::ToolAction::cancel);
        if(toolConfig_.clear())publishToolConfiguration();
    }
    void activateSweepAction(const std::string& action,size_t hand) {
        if(!sweepActionAvailable(action))return;
        const auto previous=sweepDraft_.revision;
        bool configurationChanged=false;
        if(action=="sweep:cancel") {cancelSweep();return;}
        if(action=="sweep:back") {
            if(sweepDraft_.step==2) {sweepDraft_.previous();latticeOpen_=true;}
            else {cancelSweep();return;}
        } else if(action=="sweep:confirm") {
            if(sweepDraft_.step==1) {sweepDraft_.next();latticeOpen_=false;latticePaintStroke_.reset();}
            else {
                toolShell_.apply(nadoc_vr::ToolAction::confirm,"none",true);
                publishToolIntent(nadoc_vr::ToolAction::confirm);return;
            }
        } else if(action=="sweep:free-draw") {setSweepSmoothingScale(true);sweepDraft_.armFreeDraw();}
        else if(action=="sweep:add-point") {sweepDraft_.addPoint();sweepDraft_.strokeNm.clear();}
        else if(action=="sweep:delete-point") {sweepDraft_.deleteSelectedPoint();sweepDraft_.strokeNm.clear();}
        else if(action=="sweep:delete-last-point") {sweepDraft_.deleteLastPoint();sweepDraft_.strokeNm.clear();}
        else if(action=="sweep:plane") {
            extrudePlane_.cycle();sweepDraft_.reset(sweepDefaultDirection());extrudeLatticeDraft_.clear();
            centerLatticePainting();configurationChanged=true;
        } else if(action=="sweep:strands")configurationChanged=toolConfig_.cycleOption();
        else if(action=="sweep:ligate")configurationChanged=toolConfig_.toggleFlag();
        else if(action=="sweep:paint")latticeOpen_=sweepDraft_.step==1;
        else if(action=="sweep:recenter") {recenterRequested_=true;recenterHand_=hand;}
        else if(action=="sweep:undo") {undoAuthoringTool(hand);return;}
        else if(action=="sweep:smoothing-less" || action=="sweep:smoothing-more") {
            const float delta=action=="sweep:smoothing-more"?.25F:-.25F;
            sweepDraft_.smoothingStrength=std::clamp(sweepDraft_.smoothingStrength+delta,.25F,4.F);
            setSweepSmoothingScale();
            if(!sweepDraft_.strokeInvalid && !sweepDraft_.strokeNm.empty()) {
                auto points=nadoc_vr::smoothSweepStroke(sweepDraft_.strokeNm,sweepDraft_.smoothing);
                if(points.size()>1) {sweepDraft_.pointsNm=std::move(points);sweepDraft_.selected=sweepDraft_.pointsNm.size()-1;++sweepDraft_.revision;}
            }
        } else if(action.starts_with("sweep:point:")) {
            try {sweepDraft_.select(std::stoul(action.substr(12)));}catch(const std::exception&){}
        } else if(action.starts_with("sweep:axis:")) {
            std::string fields=action.substr(11);std::replace(fields.begin(),fields.end(),':',' ');
            std::istringstream input(fields);size_t index;int axis,direction;
            if(input>>index>>axis>>direction && (direction==-1||direction==1)) {
                sweepDraft_.select(index);sweepDraft_.adjustPoint(index,axis,float(direction));
                sweepDraft_.strokeNm.clear();
            }
        }
        if(previous!=sweepDraft_.revision || configurationChanged)publishSweepDraft();
        refreshExtrudePanel();
    }
    void publishSweepDraft() {
        sweepPublishedRevision_=sweepDraft_.revision;sweepPublishedAt_=glfwGetTime();
        publishToolConfiguration();
    }
    void interruptSweepGesture() {
        if(!sweepHand_)return;
        if(sweepDraft_.drawing)sweepDraft_.cancelStroke();
        sweepHand_.reset();sweepHovered_={};
        if(sweepPanel_.active)publishSweepDraft();
    }
    void setSweepSmoothingScale(bool captureScale=false) {
        if(captureScale)sweepStrokeMetresPerNm_=std::max(1e-6F,normalizationScale_*glm::length(glm::vec3(manipulator_.transform()[0])));
        const float metresPerNm=sweepStrokeMetresPerNm_;
        auto& settings=sweepDraft_.smoothing;
        settings.smoothingRadiusNm=.036F*sweepDraft_.smoothingStrength/metresPerNm;
        settings.simplifyToleranceNm=.015F*sweepDraft_.smoothingStrength/metresPerNm;
        settings.sampleSpacingNm=.0015F/metresPerNm;
        settings.minimumStrokeLengthNm=.01F/metresPerNm;
    }
    void writeSweepConfiguration(std::ostream& out) const {
        out<<",\"extrude_from\":\""<<extrudePlane_.plane<<"\",\"strand_filter\":\""
           <<nadoc_vr::toolStrandFilterName(toolConfig_.strandFilter())<<"\",\"ligate_adjacent\":"
           <<(toolConfig_.ligateAdjacent()?"true":"false")<<",\"points_nm\":[";
        for(size_t i=0;i<sweepDraft_.pointsNm.size();++i) {
            if(i)out<<',';
            const auto p=sweepDraft_.pointsNm[i];out<<'['<<p.x<<','<<p.y<<','<<p.z<<']';
        }
        out<<"],\"painted_footprint\":{\"lattice_type\":\""<<(latticeSquare_?"SQUARE":"HONEYCOMB")<<"\",\"cells\":[";
        for(size_t i=0;i<extrudeLatticeDraft_.cells().size();++i) {
            if(i)out<<',';
            const auto cell=extrudeLatticeDraft_.cells()[i];out<<'['<<cell.row<<','<<cell.column<<']';
        }
        out<<"]}";
    }
    void writeSweepObservation(std::ostream& out) const {
        auto vector=[&](glm::vec3 p){out<<'['<<p.x<<','<<p.y<<','<<p.z<<']';};
        const auto model=sweepWorldTransform();
        auto world=[&](glm::vec3 p){return glm::vec3(model*glm::vec4(p,1));};
        out<<",\"sweep\":{\"active\":"<<(sweepPanel_.active?"true":"false")
           <<",\"step\":"<<sweepDraft_.step<<",\"selected\":"<<sweepDraft_.selected
           <<",\"free_draw_armed\":"<<(sweepDraft_.freeDrawArmed?"true":"false")
           <<",\"drawing\":"<<(sweepDraft_.drawing?"true":"false")
           <<",\"dragging\":"<<(sweepHand_ && !sweepDraft_.drawing?"true":"false")
           <<",\"preview_count\":"<<(sweepPanel_.active && sweepDraft_.step==2?sweepCloud_.size():0)
           <<",\"ready\":"<<(sweepReady()?"true":"false")<<",\"hover_point\":";
        const auto hovered=sweepHovered_[1]?sweepHovered_[1]:sweepHovered_[0];
        if(hovered)out<<*hovered;else out<<"null";
        out<<",\"smoothing_radius_nm\":"<<sweepDraft_.smoothing.smoothingRadiusNm
           <<",\"simplify_tolerance_nm\":"<<sweepDraft_.smoothing.simplifyToleranceNm
           <<",\"origin_world\":";vector(world({}));
        out<<",\"points_nm\":[";
        for(size_t i=0;i<sweepDraft_.pointsNm.size();++i){if(i)out<<',';vector(sweepDraft_.pointsNm[i]);}
        out<<"],\"points_world\":[";
        for(size_t i=0;i<sweepDraft_.pointsNm.size();++i){if(i)out<<',';vector(world(sweepDraft_.pointsNm[i]));}
        out<<"],\"stroke_world\":[";
        for(size_t i=0;i<sweepDraft_.strokeNm.size();++i){if(i)out<<',';vector(world(sweepDraft_.strokeNm[i]));}
        out<<"]}";
    }
    void processSweepInput(std::array<bool,2>& blocked,bool moving) {
        sweepHovered_={};
        if(!sweepPanel_.active)return;
        if(sweepDraft_.step!=2 || toolShell_.executionPending()) {blocked.fill(true);return;}
        if(sweepHand_) {
            const size_t h=*sweepHand_;blocked[h]=true;liveInputOwner_[h]="sweep";
            if(!hands_[h].valid || moving || manipulator_.transform()!=sweepStartModel_ || sessionState_!=XR_SESSION_STATE_FOCUSED) {
                if(sweepDraft_.drawing)sweepDraft_.cancelStroke();
                sweepHand_.reset();publishSweepDraft();blocked.fill(true);return;
            }
            const auto position=sweepRelativePoint(hands_[h].position+hands_[h].orientation*glm::vec3(0,0,-.12F));
            if(sweepDraft_.drawing) {
                sweepDraft_.appendStroke(position);
                if(!triggerPressed_[h]) {sweepDraft_.finishStroke();sweepHand_.reset();publishSweepDraft();}
            } else {
                sweepDraft_.movePoint(sweepDraft_.selected,sweepPointStart_+position-sweepDragStart_);
                if(!triggerPressed_[h]) {sweepHand_.reset();publishSweepDraft();}
            }
        } else if(!moving) {
            const auto model=sweepWorldTransform();
            std::vector<glm::vec3> points;for(const auto p:sweepDraft_.pointsNm)points.push_back(glm::vec3(model*glm::vec4(p,1)));
            for(size_t h=0;h<2;++h) {
                if(blocked[h] || !hands_[h].valid)continue;
                const auto tip=hands_[h].position+hands_[h].orientation*glm::vec3(0,0,-.12F);
                const auto hit=nadoc_vr::sweepPointRayHit(points,hands_[h].position,hands_[h].orientation*glm::vec3(0,0,-1),.016F);
                if(hit)sweepHovered_[h]=hit->index;
                if(triggerClicked_[h] && sweepDraft_.freeDrawArmed && h==1) {
                    setSweepSmoothingScale(true);sweepDraft_.beginStroke(sweepRelativePoint(tip));sweepHand_=h;
                    sweepStartModel_=manipulator_.transform();publishSweepDraft();break;
                } else if(triggerClicked_[h] && hit && !sweepDraft_.freeDrawArmed) {
                    sweepDraft_.select(hit->index);pulse(h,.2F);
                    if(hit->index) {
                        sweepHand_=h;sweepDragStart_=sweepRelativePoint(tip);sweepPointStart_=sweepDraft_.pointsNm[hit->index];
                        sweepStartModel_=manipulator_.transform();sweepDraft_.strokeNm.clear();
                    }
                    break;
                }
            }
        }
        // Scene selection cannot retarget a lattice-only authoring draft.
        blocked.fill(true);
        if(!sweepDraft_.drawing && sweepPublishedRevision_!=sweepDraft_.revision && glfwGetTime()-sweepPublishedAt_>.12)
            publishSweepDraft();
    }
    template<class Line> void drawSweep(Line line) {
        if(!sweepPanel_.active || sweepDraft_.step!=2)return;
        const auto origin=sweepOriginNm();
        const auto model=sweepWorldTransform();
        auto world=[&](glm::vec3 p){return glm::vec3(model*glm::vec4(p,1));};
        if(sweepGeometryRevision_!=sweepDraft_.revision) {
            sweepGeometryRevision_=sweepDraft_.revision;
            sweepCurve_=nadoc_vr::sampleSweepPath(sweepDraft_.pointsNm);
            std::vector<glm::vec3> offsets;for(const auto& cell:extrudeLatticeDraft_.cells())offsets.push_back(sweepCellNm(cell)-origin);
            sweepCloud_=nadoc_vr::sweepPreviewCloud(sweepDraft_.pointsNm,offsets,128,4096,glm::normalize(sweepDefaultDirection()));
        }
        const auto eyeRight=witnessObserverOrientation_*glm::vec3(1,0,0),eyeUp=witnessObserverOrientation_*glm::vec3(0,1,0);
        for(const auto p:sweepCloud_) {
            const auto q=world(p);const float r=.0015F;
            line(q-eyeRight*r,q+eyeRight*r,{.12F,.65F,.45F});
            line(q-eyeUp*r,q+eyeUp*r,{.12F,.65F,.45F});
        }
        const auto& path=sweepDraft_.drawing?sweepDraft_.strokeNm:sweepCurve_;
        // Draw the bright core first. Coplanar halo strokes write depth too;
        // drawing them first can hide the core under GL_LESS in the headset.
        for(size_t i=1;i<path.size();++i)line(world(path[i-1]),world(path[i]),{.3F,1.F,.4F});
        for(size_t i=1;i<path.size();++i) {
            const auto a=world(path[i-1]),b=world(path[i]);
            if(sweepDraft_.drawing)for(const float side:{-1.F,1.F}) {
                line(a+eyeRight*(side*.002F),b+eyeRight*(side*.002F),{.08F,.45F,.16F});
                line(a+eyeUp*(side*.002F),b+eyeUp*(side*.002F),{.08F,.45F,.16F});
            }
        }
        for(size_t i=0;i<sweepDraft_.pointsNm.size();++i) {
            const auto q=world(sweepDraft_.pointsNm[i]);
            const bool hovered=sweepHovered_[0]==i || sweepHovered_[1]==i;
            const glm::vec3 color=hovered?glm::vec3(1,1,.55F):i==sweepDraft_.selected?glm::vec3(1,.76F,.18F):glm::vec3(.3F,1,.5F);
            for(int j=0;j<24;++j) {
                const float a=glm::two_pi<float>()*j/24,b=glm::two_pi<float>()*(j+1)/24;
                line(q+.012F*(eyeRight*std::cos(a)+eyeUp*std::sin(a)),q+.012F*(eyeRight*std::cos(b)+eyeUp*std::sin(b)),color);
            }
            line(q-eyeRight*.006F,q+eyeRight*.006F,color);line(q-eyeUp*.006F,q+eyeUp*.006F,color);
        }
        for(size_t h=0;h<2;++h)if(sweepHovered_[h] || (sweepHand_==h && !sweepDraft_.drawing))
            line(hands_[h].position,world(sweepDraft_.pointsNm[sweepHand_==h?sweepDraft_.selected:*sweepHovered_[h]]),{.4F,1.F,.65F});
    }
