#pragma once
#include <GL/gl.h>
#include <array>
#include <cstddef>
#include "spectator_diagnostics.hpp"

namespace nadoc_vr {
// Tag the existing guide draw ranges without changing geometry or draw order.
// Later menu/overlay draws replace these tags wherever they cover a controller.
inline void drawClassifiedControllerGuides(
    size_t count, const std::array<size_t, 2>& handEnds) {
    size_t begin = 0;
    const std::array classes{SpectatorRenderClass::controller_left,
                             SpectatorRenderClass::controller_right};
    for (size_t hand = 0; hand < 2; ++hand) {
        glStencilFunc(GL_ALWAYS, static_cast<GLint>(classes[hand]), 0xFFU);
        glDrawArrays(GL_LINES, static_cast<GLint>(begin),
            static_cast<GLsizei>(handEnds[hand] - begin));
        begin = handEnds[hand];
    }
    glStencilFunc(GL_ALWAYS, static_cast<GLint>(SpectatorRenderClass::overlay), 0xFFU);
    glDrawArrays(GL_LINES, static_cast<GLint>(begin), static_cast<GLsizei>(count - begin));
}
}  // namespace nadoc_vr
