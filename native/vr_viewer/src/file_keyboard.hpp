// Compatibility names for existing File callers; all layout lives in the shared keyboard.
#include "text_keyboard.hpp"
inline constexpr auto kFileKeyboardScale=kTextKeyboardScale;
inline constexpr auto kFileKeyboardBounds=kTextKeyboardBounds;
inline auto fileKeyboardKeys(){return textKeyboardKeys();}
inline auto fileKeyboardControls(const SidebarTab& tab,const std::function<bool(const std::string&)>& available){return textKeyboardControls(tab,available);}

class FileHoverFeedback {
    std::string previous;
 public:
    bool enter(const std::string& target) {
        const bool changed=!target.empty() && target!=previous;
        previous=target;
        return changed;
    }
};
