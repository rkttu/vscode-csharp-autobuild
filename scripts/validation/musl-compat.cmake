# Select the existing POSIX strerror_r branch only in the affected source file.
# musl keeps the POSIX int return type even when _GNU_SOURCE is defined.
function(netcoredbg_musl_error_strings)
    set_property(SOURCE "${CMAKE_SOURCE_DIR}/src/utils/err_utils.cpp"
        DIRECTORY "${CMAKE_SOURCE_DIR}/src"
        APPEND PROPERTY COMPILE_OPTIONS -U_GNU_SOURCE -D_POSIX_C_SOURCE=200809L)
    target_sources(netcoredbg PRIVATE "${CMAKE_CURRENT_FUNCTION_LIST_DIR}/musl-coreclr-host.cpp")
    target_link_options(netcoredbg PRIVATE -Wl,--wrap=dlsym)
endfunction()
cmake_language(DEFER CALL netcoredbg_musl_error_strings)
