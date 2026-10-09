    bool moveAvailable() const {
        return movePanel_.active && !movePanel_.selecting && !toolShell_.executionPending() &&
            !moveAwaitRefresh_ && !ligation_.waiting &&
            nadoc_vr::ToolShell::selectionCapability(nadoc_vr::ToolMode::move_rotate,selectedSelectionKind_)==nadoc_vr::ToolCapability::direct_preview;
    }
    bool prepareMove() {
        if(!moveAvailable())return false;
        if(toolShell_.previewRequested())return true;
        const auto center=glScene_->ownerHandle(selectedOwnerTokens_,glm::mat4(1));
        if(!center)return false;
        movePanel_.configure(*center,sourceAxes_,normalizationScale_);
        pendingToolTransform_.activate();moveStartRevision_=sceneRefresh_.revision();
        toolShell_.apply(nadoc_vr::ToolAction::preview,selectedSelectionKind_);
        publishToolIntent(nadoc_vr::ToolAction::preview);
        return true;
    }
    void updateMovePreview() {
        const auto transform=movePanel_.transform();
        if(transform!=pendingToolTransform_.transform()) {pendingToolTransform_.setTransform(transform);publishToolTransform();}
        glScene_->setMovePointPreview(selectedOwnerTokens_,pendingToolTransform_.transform());
        movePanel_.refresh(sidebarMenus_.menus,selectedSelectionKind_,toolShell_.status());
    }
    std::optional<glm::vec3> moveRayHit() const {
        if(!hands_[1].valid)return std::nullopt;
        // Pick the visible preview, including after earlier grabs and numeric edits.
        return glScene_->pickSelected({hands_[1].position,hands_[1].orientation*glm::vec3(0,0,-1)},
            manipulator_.transform()*pendingToolTransform_.transform(),selectedOwnerTokens_);
    }
    bool beginMove(bool rotate) {
        const auto hit=moveRayHit();
        if(!hit || !prepareMove())return false;
        movePanel_.grabPoint=*hit;
        const auto center=glm::vec3(manipulator_.transform()*glm::vec4(movePanel_.pivot,1));
        movePanel_.begin(1,hands_[1],manipulator_.transform(),center,rotate);
        pulse(1,.35F);return true;
    }
    void processMoveGrip(std::array<bool,2>& blocked) {
        if(!movePanel_.active)return;
        if(movePanel_.hand && movePanel_.rotating) {
            blocked[1]=true;suppressManipulationUntilRelease_=true;return;
        }
        if(!blocked[1] && moveAvailable() && !movePanel_.moving() && gripClicked_[1] &&
            manipulator_.mode()==nadoc_vr::ManipulationMode::none && beginMove(true)) {
            blocked[1]=true;suppressManipulationUntilRelease_=true;
        }
    }
    void processMoveWheels(std::array<bool,2>& blocked) {
        if(!movePanel_.active)return;
        if(!moveAvailable() || movePanel_.hand || sessionState_!=XR_SESSION_STATE_FOCUSED) {
            movePanel_.wheelHand.reset();for(auto& w:movePanel_.wheels)w.reset();return;
        }
        const auto& menu=sidebarMenus_.menus[1];
        for(size_t h=0;h<2;++h)if(!blocked[h] && menu.open) {
            for(const auto& c:menu.controls())if(c.id.starts_with("move:") && c.id.ends_with("-wheel") &&
                nadoc_vr::thumbwheelHit(nadoc_vr::thumbwheelPreset(100,.2F),
                    {(c.bounds.minimum.x+c.bounds.maximum.x)*.5F,(c.bounds.minimum.y+c.bounds.maximum.y)*.5F,.012F},menu.placement,hands_[h])) {
                blocked[h]=true;
                if(triggerClicked_[h] && !movePanel_.wheelHand && prepareMove()) {
                    const auto point=bendWheelPoint(h);if(!point)continue;
                    movePanel_.wheelIndex=size_t(c.id[5]-'0');movePanel_.wheelHand=h;
                    movePanel_.wheels[movePanel_.wheelIndex].begin(point->y);
                }
            }
        }
        for(size_t i=0;i<6;++i) {
            auto& wheel=movePanel_.wheels[i];int steps=0;
            if(movePanel_.wheelHand && movePanel_.wheelIndex==i) {
                const auto h=*movePanel_.wheelHand;blocked[h]=true;
                if(!hands_[h].valid) {wheel.reset();movePanel_.wheelHand.reset();}
                else if(!triggerPressed_[h]) {wheel.release();movePanel_.wheelHand.reset();}
                else if(const auto point=bendWheelPoint(h))steps=wheel.drag(point->y,frameDeltaSeconds_);
                else {wheel.reset();movePanel_.wheelHand.reset();}
            }
            if(!wheel.dragging())steps+=wheel.updateMomentum(frameDeltaSeconds_);
            if(steps && prepareMove()) {movePanel_.adjust(i,steps);updateMovePreview();}
        }
    }
    void drawMoveWheels() {
        if(!movePanel_.active)return;
        const auto& menu=sidebarMenus_.menus[1];
        if(menu.open)for(const auto& c:menu.controls())if(c.id.ends_with("-wheel")) {
            const auto& wheel=movePanel_.wheels[size_t(c.id[5]-'0')];
            solidWheels_.wheel(nadoc_vr::thumbwheelPreset(100,.2F),wheel.phase(),
                {(c.bounds.minimum.x+c.bounds.maximum.x)*.5F,(c.bounds.minimum.y+c.bounds.maximum.y)*.5F,.012F},
                wheel.moving()?glm::vec3(.38F,1,.58F):glm::vec3(.54F,.70F,.84F),
                [&](auto p){return menu.placement.worldPoint(p);});
        }
    }
    void processMoveInput(std::array<bool,2>& blocked,bool sceneMoving) {
        nadoc_vr::CalculationScope auditScope("processMoveInput");
        if(!movePanel_.active)return;
        if(moveAwaitRefresh_ && !toolShell_.executionPending() &&
           (sceneRefresh_.revision()>moveStartRevision_ || toolShell_.status()=="COMMIT FAILED" || toolShell_.status()=="COMMIT REFUSED"))moveAwaitRefresh_=false;
        if(toolShell_.previewRequested() && !toolShell_.executionPending() && sceneRefresh_.revision()!=moveStartRevision_)cancelMove();
        movePanel_.refresh(sidebarMenus_.menus,selectedSelectionKind_,toolShell_.status());
        movePanel_.nearby.fill(false);movePanel_.beamEnd.reset();
        if(movePanel_.hand) {
            constexpr size_t h=1;blocked[h]=true;liveInputOwner_[h]="move-rotate";
            if(!hands_[h].valid || sessionState_!=XR_SESSION_STATE_FOCUSED ||
                (sceneMoving && !movePanel_.rotating) || !moveAvailable() ||
                manipulator_.transform()!=movePanel_.startModel || sceneRefresh_.revision()!=moveStartRevision_) {cancelMove();return;}
            movePanel_.update(hands_[h]);updateMovePreview();
            movePanel_.beamEnd=glm::vec3(manipulator_.transform()*movePanel_.transform()*glm::vec4(movePanel_.pivot,1));
            if(!(movePanel_.rotating?gripPressed_[h]:triggerPressed_[h]))movePanel_.hand.reset();
        } else if(moveAvailable() && !movePanel_.moving() && !sceneMoving && !blocked[1]) {
            movePanel_.beamEnd=moveRayHit();movePanel_.nearby[1]=movePanel_.beamEnd.has_value();
            if(movePanel_.nearby[1] && triggerClicked_[1] && beginMove(false)) {
                blocked[1]=true;liveInputOwner_[1]="move-rotate";
            }
        }
        const bool preview=toolShell_.previewRequested() &&
            (!toolShell_.executionPending() || sceneRefresh_.revision()==moveStartRevision_);
        glScene_->setMovePointPreview(preview?selectedOwnerTokens_:std::vector<std::string>{},pendingToolTransform_.transform());
    }
