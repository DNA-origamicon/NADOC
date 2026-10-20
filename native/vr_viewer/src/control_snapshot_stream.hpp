#pragma once
#include "view_snapshot_inbox.hpp"
#include <memory>
#include <filesystem>
#include <fstream>
namespace nadoc_vr {
// Preserve the presenter's existing three-second liveness timeout, including
// unchanged heartbeat packets. An established IPC channel never reads old files.
class ControlSnapshotStream {
    std::unique_ptr<ViewSnapshotInbox> inbox_;
    std::optional<std::string> latest_;
    std::chrono::steady_clock::time_point received_{};
public:
    std::optional<std::string> latest(const std::string& path) {
        if(!inbox_)inbox_=std::make_unique<ViewSnapshotInbox>(path,false);
        const auto now=std::chrono::steady_clock::now();
        if(auto packet=inbox_->take()){latest_=std::move(packet);received_=now;}
        if(inbox_->received())return now-received_<std::chrono::seconds(3)?latest_:std::nullopt;
        std::error_code error;const auto changed=std::filesystem::last_write_time(path,error);
        if(error || std::filesystem::file_time_type::clock::now()-changed>std::chrono::seconds(3))return {};
        std::ifstream in(path);return std::string(std::istreambuf_iterator<char>(in),{});
    }
};
}
