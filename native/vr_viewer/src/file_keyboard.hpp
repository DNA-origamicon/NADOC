// Included after SidebarControl. Geometry is shared by rendering and ray hits.
inline constexpr float kFileKeyboardScale=1.2F;
inline constexpr float kFileKeyPitch=.15F;
inline constexpr float kFileKeyInset=.008F;
inline constexpr MenuPanelBounds kFileKeyboardBounds{{-.945F,-.61F},{.945F,.735F}};
struct FileKey { std::string key; float column,row,width=1; };
inline std::vector<FileKey> fileKeyboardKeys() {
    std::vector<FileKey> keys;
    auto letters=[&](const std::string& text,float row,float offset) {
        for(size_t i=0;i<text.size();++i)keys.push_back({text.substr(i,1),offset+float(i),row});
    };
    letters("1234567890",0,0);keys.push_back({"delete",10,0,1.5F});
    letters("qwertyuiop",1,.25F);
    letters("asdfghjkl",2,.5F);
    keys.push_back({"shift",0,3,1.5F});letters("zxcvbnm",3,1.5F);
    keys.push_back({"dot",8.5F,3});keys.push_back({"dash",9.5F,3});
    keys.push_back({"underscore",10.5F,3});keys.push_back({"space",2,4,7.5F});
    return keys;
}
inline std::vector<SidebarControl> fileKeyboardControls(const SidebarTab& tab,
        const std::function<bool(const std::string&)>& available) {
    std::vector<SidebarControl> result;
    const auto keys=fileKeyboardKeys();
    size_t button=0;
    for(const auto& row:tab.rows) {
        MenuPanelBounds box;
        if(row.id.starts_with("routing:file-key-")) {
            const auto key=std::find_if(keys.begin(),keys.end(),[&](const auto& k){return row.id=="routing:file-key-"+k.key;});
            if(key==keys.end())continue;
            const float x=-.8625F+key->column*kFileKeyPitch;
            const float y=.20F-key->row*kFileKeyPitch;
            box={{x+kFileKeyInset,y-kFileKeyPitch+kFileKeyInset},{x+key->width*kFileKeyPitch-kFileKeyInset,y-kFileKeyInset}};
        } else if(row.id=="routing-help") box={{-.8625F,.39F},{.8625F,.52F}};
        else if(!row.action.empty()) {
            const float x=-.8625F+float(button++)*.575F;
            box={{x+.008F,.235F},{x+.567F,.365F}};
        } else continue;
        result.push_back({row.id,row.label,"",row.action,box,!row.action.empty()&&available(row.action)});
    }
    return result;
}

class FileHoverFeedback {
    std::string previous;
 public:
    bool enter(const std::string& target) {
        const bool changed=!target.empty() && target!=previous;
        previous=target;
        return changed;
    }
};
