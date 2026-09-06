# Select the existing POSIX strerror_r branch only in the affected source file.
# musl keeps the POSIX int return type even when _GNU_SOURCE is defined.
function(netcoredbg_musl_error_strings)
    set_property(SOURCE "${CMAKE_SOURCE_DIR}/src/utils/err_utils.cpp"
        DIRECTORY "${CMAKE_SOURCE_DIR}/src"
        APPEND PROPERTY COMPILE_OPTIONS -U_GNU_SOURCE)
endfunction()
cmake_language(DEFER CALL netcoredbg_musl_error_strings)
