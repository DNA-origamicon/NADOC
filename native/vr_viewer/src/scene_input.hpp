#pragma once
#include <charconv>
#include <cmath>
#include <istream>
#include <string>
#include <type_traits>

namespace nadoc_vr {
// Scene numbers are ASCII, independent of the desktop locale. Avoid the costly
// locale facet for each coordinate/color, retaining the underlying stream for
// metadata readers and gzip error handling. No read-ahead crosses a token.
class SceneInput {
    std::istream& stream_;
    std::string token_;
public:
    explicit SceneInput(std::istream& stream):stream_(stream) { token_.reserve(32); }
    explicit operator bool() const { return bool(stream_); }
    template<class T> SceneInput& operator>>(T& value) {
        if constexpr (!std::is_floating_point_v<T>) {
            stream_ >> value;
        } else {
            value=T{}; // Keep failed fields initialized until the caller checks the stream.
            if (!stream_) return *this;
            token_.clear();
            auto* buffer=stream_.rdbuf();
            auto space=[](int c){return c==' ' || c=='\n' || c=='\r' || c=='\t' || c=='\f' || c=='\v';};
            int c=buffer->sgetc();
            while(space(c))c=buffer->snextc();
            while(c!=std::char_traits<char>::eof() && !space(c)) {
                token_.push_back(char(c));c=buffer->snextc();
            }
            const char* first=token_.data();
            const char* last=first+token_.size();
            if(first!=last && *first=='+') {
                ++first;
                if(first!=last && (*first=='-' || *first=='+')) {
                    stream_.setstate(std::ios::failbit);return *this;
                }
            }
            T parsed{};
            const auto result=std::from_chars(first,last,parsed);
            if(result.ec!=std::errc{} || result.ptr!=last || !std::isfinite(parsed))
                stream_.setstate(std::ios::failbit);
            else value=parsed;
        }
        return *this;
    }
};
}
