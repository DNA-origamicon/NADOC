    glm::mat4 clipboardFrame() const {
        return manipulator_.transform()*glm::translate(glm::mat4(1),glm::vec3(0,0,-kViewDistanceMeters))
            *glm::scale(glm::mat4(1),glm::vec3(normalizationScale_))
            *glm::translate(glm::mat4(1),-normalizationCenter_);
    }
    void activateClipboard(size_t item) {
        if(!glScene_ || !ligation_.version || !hands_[1].valid)return;
        const bool accepted=item==4?clipboard_.copy({},
            committedSelectionOwnerTokens_,hands_[1],clipboardFrame()):clipboard_.paste(hands_[1],clipboardFrame());
        if(!accepted)return;
        radialToolMenu_.setPending(item);
        ligation_.request(item==4?"copy":"paste",0,[&]{publishEventState();});pulse(1U,.62F);
    }
