#pragma once
#include <optional>
#include <string>
#include <string_view>
#include <unordered_map>
#include <unordered_set>
#include <vector>

namespace nadoc_vr {
// Borrow immutable source records, like SourceIndex. Vector moves preserve
// addresses; replacement rebuilds the index before the old source is retired.
class SelectionOwnerIndex {
    std::unordered_map<std::string_view, const std::vector<std::string>*> aliases_;
    std::unordered_map<std::string_view, std::unordered_set<std::string_view>> kinds_;
public:
    template<class Aliases> void reset(const Aliases& aliases) {
        aliases_.clear(); kinds_.clear(); aliases_.reserve(aliases.size());
        for (const auto& entry : aliases) aliases_.try_emplace(entry.identity, &entry.tokens);
    }
    void addKind(std::string_view token, std::string_view kind) {
        kinds_[token].insert(kind);
    }
    std::optional<std::string> resolve(const std::string& identity,
                                        const std::string& level) const {
        const std::string kind = level == "default" ? "strand" :
            level == "xover" ? "crossover" : level;
        if (kind == "end" && identity.starts_with("segment:")) return std::nullopt;
        const auto owner = aliases_.find(identity);
        if (owner == aliases_.end()) return std::nullopt;
        std::optional<std::string> endpoint;
        for (const auto& token : *owner->second) {
            const auto typed = kinds_.find(token);
            if (typed == kinds_.end() || !typed->second.contains(kind)) continue;
            if (kind != "end") return token;
            if (endpoint && *endpoint != token) return std::nullopt;
            endpoint = token;
        }
        return endpoint;
    }
};
}
