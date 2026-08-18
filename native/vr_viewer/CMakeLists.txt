cmake_minimum_required(VERSION 3.20)
project(nadoc_vr_viewer LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

find_package(OpenGL REQUIRED)
find_package(PkgConfig REQUIRED)
pkg_check_modules(GLFW REQUIRED IMPORTED_TARGET glfw3)
pkg_check_modules(OPENXR REQUIRED IMPORTED_TARGET openxr)
pkg_check_modules(X11 REQUIRED IMPORTED_TARGET x11)

add_executable(nadoc-vr-viewer src/main.cpp)
target_link_libraries(nadoc-vr-viewer PRIVATE
  PkgConfig::OPENXR
  PkgConfig::GLFW
  PkgConfig::X11
  OpenGL::GL
)
target_compile_options(nadoc-vr-viewer PRIVATE
  -Wall -Wextra -Wpedantic -Wno-missing-field-initializers
)

install(TARGETS nadoc-vr-viewer RUNTIME DESTINATION bin)
