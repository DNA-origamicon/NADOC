#pragma once
#include <array>
#include <cstdint>

namespace nadoc_vr {
inline std::array<uint8_t, 7> glyph(char value) {
    switch (value) {
        case 'A': return {14, 17, 17, 31, 17, 17, 17};
        case 'B': return {30, 17, 17, 30, 17, 17, 30};
        case 'C': return {14, 17, 16, 16, 16, 17, 14};
        case 'D': return {30, 17, 17, 17, 17, 17, 30};
        case 'E': return {31, 16, 16, 30, 16, 16, 31};
        case 'F': return {31, 16, 16, 30, 16, 16, 16};
        case 'G': return {14, 17, 16, 23, 17, 17, 14};
        case 'H': return {17, 17, 17, 31, 17, 17, 17};
        case 'I': return {31, 4, 4, 4, 4, 4, 31};
        case 'J': return {7, 2, 2, 2, 18, 18, 12};
        case 'Q': return {14, 17, 17, 17, 21, 18, 13};
        case 'K': return {17, 18, 20, 24, 20, 18, 17};
        case 'L': return {16, 16, 16, 16, 16, 16, 31};
        case 'M': return {17, 27, 21, 21, 17, 17, 17};
        case 'N': return {17, 25, 21, 19, 17, 17, 17};
        case 'O': return {14, 17, 17, 17, 17, 17, 14};
        case 'P': return {30, 17, 17, 30, 16, 16, 16};
        case 'R': return {30, 17, 17, 30, 20, 18, 17};
        case 'S': return {15, 16, 16, 14, 1, 1, 30};
        case 'T': return {31, 4, 4, 4, 4, 4, 4};
        case 'U': return {17, 17, 17, 17, 17, 17, 14};
        case 'V': return {17, 17, 17, 17, 17, 10, 4};
        case 'W': return {17, 17, 17, 21, 21, 21, 10};
        case 'X': return {17, 17, 10, 4, 10, 17, 17};
        case 'Y': return {17, 17, 10, 4, 4, 4, 4};
        case 'Z': return {31, 1, 2, 4, 8, 16, 31};
        case '0': return {14, 17, 19, 21, 25, 17, 14};
        case '1': return {4, 12, 4, 4, 4, 4, 14};
        case '2': return {14, 17, 1, 2, 4, 8, 31};
        case '3': return {30, 1, 1, 14, 1, 1, 30};
        case '4': return {2, 6, 10, 18, 31, 2, 2};
        case '5': return {31, 16, 16, 30, 1, 1, 30};
        case '6': return {14, 16, 16, 30, 17, 17, 14};
        case '7': return {31, 1, 2, 4, 8, 8, 8};
        case '8': return {14, 17, 17, 14, 17, 17, 14};
        case '9': return {14, 17, 17, 15, 1, 1, 14};
        case '+': return {0, 4, 4, 31, 4, 4, 0};
        case '-': return {0, 0, 0, 31, 0, 0, 0};
        case ' ': return {};
        case '.': return {0,0,0,0,0,12,12};
        case ',': return {0,0,0,0,12,12,8};
        case ':': return {0,12,12,0,12,12,0};
        case ';': return {0,12,12,0,12,12,8};
        case '/': return {1,2,2,4,8,8,16};
        case '\\': return {16,8,8,4,2,2,1};
        case '&': return {12,18,20,8,21,18,13};
        case '(': return {2,4,8,8,8,4,2};
        case ')': return {8,4,2,2,2,4,8};
        case '[': return {14,8,8,8,8,8,14};
        case ']': return {14,2,2,2,2,2,14};
        case '{': return {3,4,4,8,4,4,3};
        case '}': return {24,4,4,2,4,4,24};
        case '=': return {0,0,31,0,31,0,0};
        case '<': return {1,2,4,8,4,2,1};
        case '>': return {16,8,4,2,4,8,16};
        case '%': return {17,18,2,4,8,9,17};
        case '#': return {10,10,31,10,31,10,10};
        case '_': return {0,0,0,0,0,0,31};
        case '!': return {4,4,4,4,4,0,4};
        case '?': return {14,17,1,2,4,0,4};
        case '*': return {0,21,14,31,14,21,0};
        case '|': return {4,4,4,4,4,4,4};
        case '\'': return {4,4,8,0,0,0,0};
        case '"': return {10,10,10,0,0,0,0};
        case '^': return {4,10,17,0,0,0,0};
        case '~': return {0,0,9,22,0,0,0};
        case '@': return {14,17,23,21,23,16,14};
        default: return {14,17,1,2,4,0,4};
    }
}
}
