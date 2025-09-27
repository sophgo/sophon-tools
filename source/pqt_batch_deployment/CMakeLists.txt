cmake_minimum_required(VERSION 3.5)

project(qt_batch_deployment VERSION 0.1 LANGUAGES CXX)

set(CMAKE_AUTOUIC ON)
set(CMAKE_AUTOMOC ON)
set(CMAKE_AUTORCC ON)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# 配置QT cmake的路径
if(CMAKE_SYSTEM_NAME MATCHES "Windows")
  # 将C:/Qt/5.15.2/mingw81_64类似的目录添加到QT_PLATFORM_DIR的环境变量中，优先准备一个静态编译的qt库
  set(CMAKE_PREFIX_PATH "$ENV{QT_PLATFORM_DIR}")
  message(STATUS "CMAKE_PREFIX_PATH: ${CMAKE_PREFIX_PATH}")
  # 将C:/Qt/Tools/mingw810_64/bin类似的目录添加到QT_GCC_PLATFORM_DIR的环境变量中
  set(MY_GCC_PATH_ "$ENV{QT_GCC_PLATFORM_DIR}")
  if(NOT "${MY_GCC_PATH_}" STREQUAL "")
    string(REPLACE "\\" "\\\\" MY_GCC_PATH ${MY_GCC_PATH_})
  else()
    set(MY_GCC_PATH "")
  endif()
  message(STATUS "MY_GCC_PATH: ${MY_GCC_PATH}")
endif(CMAKE_SYSTEM_NAME MATCHES "Windows")
find_package(QT NAMES Qt6 Qt5 REQUIRED COMPONENTS Widgets)
find_package(Qt${QT_VERSION_MAJOR} REQUIRED COMPONENTS Widgets)

set(MY_PROJECT_VERSION "V1.4.1")
configure_file(
  "${CMAKE_SOURCE_DIR}/version.h.in"
  "${CMAKE_BINARY_DIR}/version.h"
)
include_directories(${CMAKE_BINARY_DIR})
if(CMAKE_BUILD_TYPE STREQUAL "Debug")
  message(STATUS "ues debug libs")
  # message(FATAL_ERROR "Debug mode is not supported by default. You need to add the debug libraries and modify the CMakeLists.txt file accordingly.")
  set(MYCMAKE_LIBS_TYPE "release")
else()
  message(STATUS "ues release libs")
  set(MYCMAKE_LIBS_TYPE "release")
endif(CMAKE_BUILD_TYPE STREQUAL "Debug")

if(CMAKE_SYSTEM_NAME MATCHES "Linux")
  if(CMAKE_HOST_SYSTEM_PROCESSOR MATCHES "aarch64")
    message(STATUS "current platform: Linux arm64")
    set(MYCMAKE_MATCHES "linux_arm64")
  elseif(CMAKE_HOST_SYSTEM_PROCESSOR MATCHES "x86_64")
    message(STATUS "current platform: Linux amd64")
    set(MYCMAKE_MATCHES "linux_amd64")
  endif(CMAKE_HOST_SYSTEM_PROCESSOR MATCHES "aarch64")
elseif(CMAKE_SYSTEM_NAME MATCHES "Windows")
  message(STATUS "current platform: Windows")
  set(MYCMAKE_MATCHES "win_amd64")
  get_target_property(QtWidgets_TYPE Qt5::Widgets TYPE)
  if(QtWidgets_TYPE STREQUAL "STATIC_LIBRARY")
    # 静态链接所有库（包括 GCC 运行时）
    message(STATUS "Qt is built as static libraries, use -static for gcc libs")
    set(CMAKE_EXE_LINKER_FLAGS "${CMAKE_EXE_LINKER_FLAGS} -static")
    set(CMAKE_SHARED_LINKER_FLAGS "${CMAKE_SHARED_LINKER_FLAGS} -static")
    set(CMAKE_MODULE_LINKER_FLAGS "${CMAKE_MODULE_LINKER_FLAGS} -static")
  endif()
endif(CMAKE_SYSTEM_NAME MATCHES "Linux")

message(STATUS "MYCMAKE_MATCHES:${MYCMAKE_MATCHES}")
message(STATUS "MYCMAKE_LIBS_TYPE:${MYCMAKE_LIBS_TYPE}")

set(original_path "${CMAKE_SOURCE_DIR}/libs/${MYCMAKE_MATCHES}/${MYCMAKE_LIBS_TYPE}")
get_filename_component(MY_LIB_CMAKE_PREFIX_PATH ${original_path} REALPATH)
set(CMAKE_PREFIX_PATH "${CMAKE_PREFIX_PATH};${MY_LIB_CMAKE_PREFIX_PATH}")
message(STATUS "MY_LIB_CMAKE_PREFIX_PATH:${MY_LIB_CMAKE_PREFIX_PATH}")
find_package(Libssh2 CONFIG REQUIRED)
qt5_add_resources(PROJECT_RESOURCES ${CMAKE_CURRENT_SOURCE_DIR}/resources.qrc)

set(PROJECT_SOURCES
        main.cpp
        mainwindow.cpp
        mainwindow.h
        mainwindow.ui
)

if(${QT_VERSION_MAJOR} GREATER_EQUAL 6)
    qt_add_executable(qt_batch_deployment
        MANUAL_FINALIZATION
        ${PROJECT_SOURCES}
        ${PROJECT_RESOURCES}
    )
# Define target properties for Android with Qt 6 as:
#    set_property(TARGET qt_batch_deployment APPEND PROPERTY QT_ANDROID_PACKAGE_SOURCE_DIR
#                 ${CMAKE_CURRENT_SOURCE_DIR}/android)
# For more information, see https://doc.qt.io/qt-6/qt-add-executable.html#target-creation
else()
    if(ANDROID)
        add_library(qt_batch_deployment SHARED
            ${PROJECT_SOURCES}
        )
# Define properties for Android with Qt 5 after find_package() calls as:
#    set(ANDROID_PACKAGE_SOURCE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/android")
    else()
        add_executable(qt_batch_deployment
            ${PROJECT_SOURCES}
            ${PROJECT_RESOURCES}
            tableDelegates.h
            datatypes.h
            remotesshoperation.h remotesshoperation.cpp
        )
    endif()
endif()

target_link_libraries(qt_batch_deployment PRIVATE Qt${QT_VERSION_MAJOR}::Widgets)

# edit by user
if(CMAKE_SYSTEM_NAME MATCHES "Linux")
  if(CMAKE_HOST_SYSTEM_PROCESSOR MATCHES "aarch64")
    target_link_libraries(qt_batch_deployment PRIVATE Libssh2::libssh2_shared)
  elseif(CMAKE_HOST_SYSTEM_PROCESSOR MATCHES "x86_64")
    target_link_libraries(qt_batch_deployment PRIVATE Libssh2::libssh2_shared)
  endif(CMAKE_HOST_SYSTEM_PROCESSOR MATCHES "aarch64")
elseif(CMAKE_SYSTEM_NAME MATCHES "Windows")
  target_link_libraries(qt_batch_deployment PRIVATE WS2_32.lib)
  target_link_libraries(qt_batch_deployment PRIVATE Libssh2::libssh2_static)
  get_target_property(qmake_exec_filepath Qt5::qmake IMPORTED_LOCATION)
  get_filename_component(qt_exec_bin_dir "${qmake_exec_filepath}" DIRECTORY)
  find_program(windeployqt_exec_filepath windeployqt HINTS "${qt_exec_bin_dir}")
  message(STATUS "find windeployqt ${windeployqt_exec_filepath}")
  message(STATUS "MY_GCC_PATH:${MY_GCC_PATH}")
  set(enigma_virtual_box_com_path "${MY_LIB_CMAKE_PREFIX_PATH}/../enigmavbconsole.exe")
  message(STATUS "enigma_virtual_box_com_path:${enigma_virtual_box_com_path}")
  set(7z_tool_path "${MY_LIB_CMAKE_PREFIX_PATH}/../7z.exe")
  message(STATUS "7z_tool_path:${7z_tool_path}")
  set(MY_OUTPUT_NAME "qt_batch_deployment_${MY_PROJECT_VERSION}.exe")
  message(STATUS "MY_OUTPUT_NAME:${MY_OUTPUT_NAME}")
  if(QtWidgets_TYPE STREQUAL "STATIC_LIBRARY")
    message(STATUS "Qt is built as static libraries")
    install(CODE "execute_process(COMMAND \"${CMAKE_COMMAND}\" -E copy \"${CMAKE_BINARY_DIR}/qt_batch_deployment.exe\" \"${CMAKE_BINARY_DIR}/output/${MY_OUTPUT_NAME}\")")
  else()
    message(STATUS "Qt is built as shared libraries")
    file(COPY "${MY_LIB_CMAKE_PREFIX_PATH}/../qt_batch_deployment_boxed.evb" DESTINATION "${CMAKE_BINARY_DIR}")
    file(READ "${CMAKE_BINARY_DIR}/qt_batch_deployment_boxed.evb" SOURCE_CONTENT)
    string(REPLACE "__build_output__" "${CMAKE_BINARY_DIR}\\output" MODIFIED_CONTENT "${SOURCE_CONTENT}")
    file(WRITE "${CMAKE_BINARY_DIR}/qt_batch_deployment_boxed.evb" "${MODIFIED_CONTENT}")
    set(MY_POWSHELL_COM "& \"'${enigma_virtual_box_com_path}'\" \"${CMAKE_BINARY_DIR}/qt_batch_deployment_boxed.evb\" -output \"${CMAKE_BINARY_DIR}/output/${MY_OUTPUT_NAME}\"")
    message(STATUS "MY_POWSHELL_COM:${MY_POWSHELL_COM}")
    install(CODE "execute_process(COMMAND \"${CMAKE_COMMAND}\" -E make_directory \"${CMAKE_BINARY_DIR}/output/libs\")")
    install(CODE "execute_process(COMMAND \"${CMAKE_COMMAND}\" -E copy_directory \"${MY_LIB_CMAKE_PREFIX_PATH}/../openssl/bin\" \"${CMAKE_BINARY_DIR}/output/libs\")")
    install(CODE "execute_process(COMMAND \"${CMAKE_COMMAND}\" -E copy \"${CMAKE_BINARY_DIR}/qt_batch_deployment.exe\" \"${CMAKE_BINARY_DIR}/output\")")
    install(CODE "execute_process(COMMAND \"${CMAKE_COMMAND}\" -E env PATH=\"${MY_GCC_PATH}\"  \"${windeployqt_exec_filepath}\" --release --dir \"${CMAKE_BINARY_DIR}/output/libs\" \"qt_batch_deployment.exe\")")
    install(CODE "execute_process(COMMAND \"${CMAKE_COMMAND}\" -E copy \"${CMAKE_BINARY_DIR}/qt_batch_deployment.exe\" \"${CMAKE_BINARY_DIR}/output\")")
    install(CODE "execute_process(COMMAND powershell ${MY_POWSHELL_COM})")
  endif()
endif(CMAKE_SYSTEM_NAME MATCHES "Linux")
# edit by user

# Qt for iOS sets MACOSX_BUNDLE_GUI_IDENTIFIER automatically since Qt 6.1.
# If you are developing for iOS or macOS you should consider setting an
# explicit, fixed bundle identifier manually though.
if(${QT_VERSION} VERSION_LESS 6.1.0)
  set(BUNDLE_ID_OPTION MACOSX_BUNDLE_GUI_IDENTIFIER com.example.qt_batch_deployment)
endif()
set_target_properties(qt_batch_deployment PROPERTIES
    ${BUNDLE_ID_OPTION}
    MACOSX_BUNDLE_BUNDLE_VERSION ${PROJECT_VERSION}
    MACOSX_BUNDLE_SHORT_VERSION_STRING ${PROJECT_VERSION_MAJOR}.${PROJECT_VERSION_MINOR}
    MACOSX_BUNDLE TRUE
    WIN32_EXECUTABLE TRUE
)

include(GNUInstallDirs)
install(TARGETS qt_batch_deployment
    BUNDLE DESTINATION "${CMAKE_BINARY_DIR}/output"
    LIBRARY DESTINATION "${CMAKE_BINARY_DIR}/output"
    RUNTIME DESTINATION "${CMAKE_BINARY_DIR}/output"
)

if(QT_VERSION_MAJOR EQUAL 6)
    qt_finalize_executable(qt_batch_deployment)
endif()
