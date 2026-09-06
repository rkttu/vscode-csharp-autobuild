# Add a linked dyld interposer, with no edits to Samsung's original source files.
function(netcoredbg_darwin_exit_codes)
    cmake_policy(SET CMP0079 NEW)
    # Upstream adds this executable-only switch globally. Keep its src directory
    # unchanged, but remove the switch in this library's parent directory.
    string(REPLACE "-force_flat_namespace" "" compat_cxx_flags "${CMAKE_CXX_FLAGS}")
    set(CMAKE_CXX_FLAGS "${compat_cxx_flags}" PARENT_SCOPE)
    add_library(netcoredbg_darwin_compat SHARED "${CMAKE_CURRENT_FUNCTION_LIST_DIR}/darwin-waitpid.cpp")
    set_target_properties(netcoredbg_darwin_compat PROPERTIES
        OUTPUT_NAME netcoredbg-darwin-compat
        INSTALL_NAME_DIR "@rpath"
        BUILD_WITH_INSTALL_NAME_DIR TRUE)
    target_sources(netcoredbg PRIVATE "${CMAKE_CURRENT_FUNCTION_LIST_DIR}/darwin-exit-observer.cpp")
    target_link_libraries(netcoredbg netcoredbg_darwin_compat)
    target_link_options(netcoredbg PRIVATE -Wl,-twolevel_namespace)
    set_property(TARGET netcoredbg APPEND PROPERTY INSTALL_RPATH "@loader_path")
    install(TARGETS netcoredbg_darwin_compat DESTINATION "${CMAKE_INSTALL_PREFIX}")
endfunction()
cmake_language(DEFER CALL netcoredbg_darwin_exit_codes)
