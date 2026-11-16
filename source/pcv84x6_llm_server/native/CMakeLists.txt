cmake_minimum_required(VERSION 3.10)
project(cv84x6_llm CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()

# libsophon ships the bmrt/bmlib headers and libs; no sail, no Python.
set(LIBSOPHON /opt/sophon/libsophon-current CACHE PATH "libsophon install prefix")
include_directories(${LIBSOPHON}/include ${CMAKE_CURRENT_SOURCE_DIR}/include)
link_directories(${LIBSOPHON}/lib)

add_library(cv84x6_llm SHARED src/llm_engine.cpp src/c_api.cpp src/tokenizer.cpp
                          src/vision.cpp src/embed_engine.cpp src/rerank_engine.cpp
                          src/asr_engine.cpp src/net_engine.cpp src/vl_engine.cpp
                          src/vl_embed_engine.cpp src/vl_embed_c_api.cpp)
target_compile_options(cv84x6_llm PRIVATE -Wall -Wextra)

# zlib for PNG inflate; libjpeg for JPEG decode (the same libjpeg-turbo the
# reference Pillow links, so coefficients and IDCT match rather than merely
# resemble). The SDK image ships both runtime objects but not the bare
# libjpeg.so linker symlink, so resolve the versioned soname by path.
find_library(ZLIB_LIB NAMES z)
if(NOT ZLIB_LIB)
  set(ZLIB_LIB z)
endif()

find_library(JPEG_LIB NAMES jpeg)
if(NOT JPEG_LIB)
  # No -dev package: locate libjpeg.so.<N> and link it by full path.
  file(GLOB _jpeg_candidates
       /lib/*/libjpeg.so.8 /usr/lib/*/libjpeg.so.8
       /lib/*/libjpeg.so.62 /usr/lib/*/libjpeg.so.62)
  list(SORT _jpeg_candidates)
  list(GET _jpeg_candidates 0 JPEG_LIB)
endif()
if(NOT JPEG_LIB)
  message(FATAL_ERROR "libjpeg not found; image input needs it (native/src/vision.cpp)")
endif()
message(STATUS "vision deps: jpeg=${JPEG_LIB} zlib=${ZLIB_LIB}")

target_link_libraries(cv84x6_llm PUBLIC bmrt bmlib pthread ${JPEG_LIB} ${ZLIB_LIB})
set_target_properties(cv84x6_llm PROPERTIES
  BUILD_RPATH "${LIBSOPHON}/lib"
  INSTALL_RPATH "${LIBSOPHON}/lib")
