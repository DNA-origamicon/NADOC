    std::vector<nadoc_vr::ClipboardPreview::Segment> clipboardGeometry(const glm::mat4& model) const {
        const auto& source=currentSource();
        std::vector<nadoc_vr::ClipboardPreview::Segment> result;
        size_t seen=0,stride=1;
        auto add=[&](const std::string& id,glm::vec3 a,glm::vec3 b) {
            auto alias=sourceIndex_->aliases.find(id);
            if(alias==sourceIndex_->aliases.end() || !std::any_of(alias->second->tokens.begin(),alias->second->tokens.end(),
                [&](const auto& t){return selectedHighlightOwnerTokens_.contains(t);}))return;
            const size_t index=seen++;
            if(index%stride)return;
            if(result.size()==8192) {
                for(size_t i=0;i<4096;++i)result[i]=result[i*2];
                result.resize(4096);stride*=2;
                if(index%stride)return;
            }
            a=glm::vec3(model*glm::vec4(displayedPoint(source,a,id),1));
            b=glm::vec3(model*glm::vec4(displayedPoint(source,b,id,true),1));
            result.emplace_back(a,b);
        };
        for(const auto& c:source.cylinders)add(c.identity,c.start,c.end);
        for(const auto& c:source.halfCylinders)add(c.identity,c.start,c.end);
        for(const auto& b:source.boxes)add(b.identity,b.center-b.axisZ,b.center+b.axisZ);
        for(const auto& p:source.points)add(p.identity,p.position-glm::vec3(.001F,0,0),p.position+glm::vec3(.001F,0,0));
        return result;
    }
