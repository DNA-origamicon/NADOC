// Capability-only NvFBC probe. It never creates a capture session or grabs pixels.
// Build with an NVIDIA NvFBC 1.9 header supplied explicitly through -I:
//   c++ -std=c++17 -Wall -Wextra -Werror -I/path/to/header nvfbc_probe.cpp -ldl -o nvfbc_probe
// The investigated NVIDIA-authored MIT header is mirrored at:
// https://raw.githubusercontent.com/t1stm/nvfbc-v4l2/2bcf427b97ab4d1bad999f79411a66659e64cbf9/NvFBC.h
// SHA256: f6f8b21b9f05b7e24c77e5d9c6d141ddf01c606b71e6fe5e74426c0cc128cee6
// Its ABI has not been independently compared with the gated official SDK package.
// No SDK license acceptance, privateData override, driver patch, or fallback is used.
// CreateHandle allocates a temporary graphics context; GetStatus may send a bounded
// D-Bus status request to the target. Coordinate this probe with timing experiments.

#include <NvFBC.h>
#include <dlfcn.h>

#include <algorithm>
#include <charconv>
#include <chrono>
#include <cstdint>
#include <iostream>
#include <string>
#include <string_view>

static_assert(NVFBC_VERSION_MAJOR == 1 && NVFBC_VERSION_MINOR == 9,
              "Review the probe before using a different NvFBC ABI");

namespace {
using Clock = std::chrono::steady_clock;

std::string quote(std::string_view input) {
    std::string result = "\"";
    constexpr char hex[] = "0123456789abcdef";
    for (unsigned char c : input) {
        if (c == '"' || c == '\\') {
            result += '\\';
            result += static_cast<char>(c);
        } else if (c < 0x20 || c >= 0x7f) {
            result += "\\u00";
            result += hex[c >> 4];
            result += hex[c & 15];
        } else {
            result += static_cast<char>(c);
        }
    }
    return result + '"';
}

const char* boolJson(NVFBC_BOOL value) { return value == NVFBC_TRUE ? "true" : "false"; }

void event(const char* stage, int code, Clock::time_point start,
           const char* error = "", const std::string& fields = "") {
    auto elapsed = std::chrono::duration_cast<std::chrono::microseconds>(Clock::now() - start);
    std::cout << "{\"stage\":" << quote(stage) << ",\"status\":" << code
              << ",\"elapsed_us\":" << elapsed.count()
              << ",\"error\":" << quote(error ? error : "") << fields << "}\n";
    std::cout.flush();
}

bool parsePid(std::string_view input, uint32_t& pid) {
    auto parsed = std::from_chars(input.data(), input.data() + input.size(), pid);
    return parsed.ec == std::errc{} && parsed.ptr == input.data() + input.size() && pid > 0;
}

void usage() {
    std::cerr << "Usage: nvfbc_probe --pid PID [--backend direct|x11]\n"
                 "Emits JSONL. Probes capabilities only; never records images.\n"
                 "Exit 0: driver reports capture possible now; 2: unavailable/error; 64: usage.\n"
                 "Direct mode uses EGL and a 1000 ms D-Bus status timeout.\n";
}
} // namespace

int main(int argc, char** argv) {
    uint32_t pid = 0;
    NVFBC_BACKEND backend = NVFBC_BACKEND_DIRECT;
    for (int i = 1; i < argc; ++i) {
        std::string_view arg(argv[i]);
        if (arg == "--help") { usage(); return 0; }
        if (arg == "--pid" && i + 1 < argc) {
            if (!parsePid(argv[++i], pid)) { usage(); return 64; }
        } else if (arg == "--backend" && i + 1 < argc) {
            std::string_view value(argv[++i]);
            if (value == "direct") backend = NVFBC_BACKEND_DIRECT;
            else if (value == "x11") backend = NVFBC_BACKEND_X11;
            else { usage(); return 64; }
        } else { usage(); return 64; }
    }
    if (!pid) { usage(); return 64; }
    std::cout << "{\"stage\":\"request\",\"pid\":" << pid
              << ",\"backend\":" << static_cast<int>(backend)
              << ",\"api_version\":" << NVFBC_VERSION
              << ",\"create_handle_struct_version\":" << NVFBC_CREATE_HANDLE_PARAMS_VER
              << ",\"get_status_struct_version\":" << NVFBC_GET_STATUS_PARAMS_VER
              << ",\"capture_session_created\":false,\"pixels_captured\":false}\n";
    std::cout.flush();

    auto start = Clock::now();
    // Keep the loader reference until process exit: driver-created teardown
    // callbacks may outlive temporary handles, so avoid premature ICD unload.
    void* library = dlopen("libnvidia-fbc.so.1", RTLD_NOW | RTLD_LOCAL);
    if (!library) { event("dlopen", -1, start, dlerror()); return 2; }
    auto createInstance = reinterpret_cast<PNVFBCCREATEINSTANCE>(dlsym(library, "NvFBCCreateInstance"));
    if (!createInstance) { event("dlsym", -1, start, dlerror()); return 2; }
    NVFBC_API_FUNCTION_LIST api{};
    api.dwVersion = NVFBC_VERSION;
    start = Clock::now();
    auto result = createInstance(&api);
    event("create_instance", result, start);
    if (result != NVFBC_SUCCESS) return 2;
    if (!api.nvFBCCreateHandle || !api.nvFBCDestroyHandle || !api.nvFBCGetStatus ||
        !api.nvFBCGetLastErrorStr) {
        event("function_table", -1, Clock::now(), "Required capability entry point absent");
        return 2;
    }

    NVFBC_SESSION_HANDLE handle = 0;
    NVFBC_CREATE_HANDLE_PARAMS create{};
    create.dwVersion = NVFBC_CREATE_HANDLE_PARAMS_VER;
    create.eBackend = backend;
    create.bUseEGL = backend == NVFBC_BACKEND_DIRECT ? NVFBC_TRUE : NVFBC_FALSE;
    start = Clock::now();
    result = api.nvFBCCreateHandle(&handle, &create);
    // A failed create has no valid handle to query for an error message.
    event("create_handle", result, start, "", ",\"selected_backend\":" + std::to_string(create.eBackend));
    if (result != NVFBC_SUCCESS) return 2;

    NVFBC_GET_STATUS_PARAMS status{};
    status.dwVersion = NVFBC_GET_STATUS_PARAMS_VER;
    status.dwPid = pid;
    status.dwDbusTimeoutMs = 1000;
    start = Clock::now();
    result = api.nvFBCGetStatus(handle, &status);
    std::string fields;
    if (result == NVFBC_SUCCESS) {
        fields = std::string(",\"capture_possible\":") + boolJson(status.bIsCapturePossible)
               + ",\"currently_capturing\":" + boolJson(status.bCurrentlyCapturing)
               + ",\"can_create_now\":" + boolJson(status.bCanCreateNow)
               + ",\"in_modeset\":" + boolJson(status.bInModeset)
               + ",\"library_version\":" + std::to_string(status.dwNvFBCVersion)
               + ",\"capture_target_count\":" + std::to_string(status.dwCaptureTargetCount)
               + ",\"capture_target_sizes\":[";
        for (uint32_t i = 0; i < std::min<uint32_t>(status.dwCaptureTargetCount, NVFBC_DIRECT_MAX_CAPTURE_TARGETS); ++i) {
            if (i) fields += ',';
            fields += '[' + std::to_string(status.captureTargetSizes[i].w) + ','
                    + std::to_string(status.captureTargetSizes[i].h) + ']';
        }
        fields += ']';
    }
    event("get_status", result, start,
          result == NVFBC_SUCCESS ? "" : api.nvFBCGetLastErrorStr(handle), fields);
    bool usable = result == NVFBC_SUCCESS && status.bIsCapturePossible == NVFBC_TRUE
               && status.bCanCreateNow == NVFBC_TRUE && status.dwCaptureTargetCount <= NVFBC_DIRECT_MAX_CAPTURE_TARGETS;
    if (backend == NVFBC_BACKEND_DIRECT) usable = usable && status.dwCaptureTargetCount > 0;

    NVFBC_DESTROY_HANDLE_PARAMS destroy{};
    destroy.dwVersion = NVFBC_DESTROY_HANDLE_PARAMS_VER;
    start = Clock::now();
    result = api.nvFBCDestroyHandle(handle, &destroy);
    event("destroy_handle", result, start);
    return usable && result == NVFBC_SUCCESS ? 0 : 2;
}
