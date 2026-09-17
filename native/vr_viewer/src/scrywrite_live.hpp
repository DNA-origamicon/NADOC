#pragma once

// Linux-only, explicitly enabled development endpoint. All handlers execute on
// the viewer thread; slow/partial clients never block the OpenXR frame loop.
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <unistd.h>
#include <fcntl.h>
#include <cerrno>
#include <chrono>
#include <cstring>
#include <filesystem>
#include <functional>
#include <stdexcept>
#include <string>

namespace nadoc_vr::scrywrite {
class LiveSocket {
 public:
    LiveSocket() = default;
    LiveSocket(const LiveSocket&) = delete;
    LiveSocket& operator=(const LiveSocket&) = delete;
    ~LiveSocket() {
        closeClient();
        if (server_ >= 0) { ::close(server_); ::unlink(path_.c_str()); }
    }
    void open(const std::string& path) {
        if (server_ >= 0) throw std::runtime_error("live socket already open");
        const auto parent = std::filesystem::path(path).parent_path();
        struct stat info{};
        if (!std::filesystem::path(path).is_absolute() ||
            ::lstat(parent.c_str(), &info) != 0 || !S_ISDIR(info.st_mode) ||
            info.st_uid != ::geteuid() || (info.st_mode & 0077) != 0) {
            throw std::runtime_error("ScryWrite requires an absolute socket path in an owned private (0700) directory");
        }
        sockaddr_un address{};
        address.sun_family = AF_UNIX;
        if (path.size() >= sizeof(address.sun_path)) throw std::runtime_error("live socket path too long");
        std::memcpy(address.sun_path, path.c_str(), path.size() + 1);
        const int fd = ::socket(AF_UNIX, SOCK_STREAM | SOCK_NONBLOCK | SOCK_CLOEXEC, 0);
        if (fd < 0) throw std::runtime_error("cannot create live socket");
        // Never replace another viewer's socket or remove an arbitrary file.
        if (::bind(fd, reinterpret_cast<sockaddr*>(&address), sizeof(address)) != 0) {
            ::close(fd); throw std::runtime_error("cannot bind live socket (path must not exist)");
        }
        if (::chmod(path.c_str(), 0600) != 0 || ::listen(fd, 4) != 0) {
            ::close(fd); ::unlink(path.c_str()); throw std::runtime_error("cannot listen on live socket");
        }
        path_ = path; server_ = fd;
    }
    bool enabled() const { return server_ >= 0; }
    void poll(const std::function<std::string(const std::string&)>& handler) {
        if (!enabled()) return;
        if (client_ < 0) {
            client_ = ::accept4(server_, nullptr, nullptr, SOCK_NONBLOCK | SOCK_CLOEXEC);
            if (client_ < 0) return;
            deadline_ = std::chrono::steady_clock::now() + std::chrono::seconds(2);
        }
        if (std::chrono::steady_clock::now() > deadline_) { closeClient(); return; }
        if (output_.empty()) {
            char buffer[4096];
            const auto count = ::recv(client_, buffer, sizeof(buffer), 0);
            if (count == 0 || (count < 0 && errno != EAGAIN && errno != EWOULDBLOCK)) { closeClient(); return; }
            if (count > 0) input_.append(buffer, static_cast<size_t>(count));
            if (input_.size() > 4096) { closeClient(); return; }
            const auto newline = input_.find('\n');
            if (newline == std::string::npos) return;
            if (newline != input_.size() - 1 || input_.find('\0') != std::string::npos) {
                output_ = "{\"error\":\"invalid_framing\"}";
            } else {
                try { output_ = handler(input_.substr(0, newline)); }
                catch (...) { output_ = "{\"error\":\"invalid_command\"}"; }
            }
            if (output_.size() > 1024 * 1024) output_ = "{\"error\":\"response_too_large\"}";
            output_ += '\n';
        }
        const auto count = ::send(client_, output_.data() + sent_, output_.size() - sent_, MSG_NOSIGNAL);
        if (count > 0) sent_ += static_cast<size_t>(count);
        else if (count < 0 && errno != EAGAIN && errno != EWOULDBLOCK) { closeClient(); return; }
        if (sent_ == output_.size()) closeClient();
    }
 private:
    void closeClient() {
        if (client_ >= 0) ::close(client_);
        client_ = -1; input_.clear(); output_.clear(); sent_ = 0;
    }
    int server_ = -1, client_ = -1;
    std::string path_, input_, output_;
    size_t sent_ = 0;
    std::chrono::steady_clock::time_point deadline_{};
};
} // namespace nadoc_vr::scrywrite
