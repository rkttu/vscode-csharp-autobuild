// Copyright (c) 2026 vscode-csharp-autobuild contributors. MIT License.
// Mach-O's two-level namespace does not route CoreCLR's waitpid through the
// executable's ELF-style hook. Observe libc calls without consuming extra waits.
#include <cerrno>
#include <sys/wait.h>

using ExitObserver = void (*)(pid_t, int);
static ExitObserver observer = nullptr;

extern "C" void autobuild_set_exit_observer(ExitObserver callback)
{
    observer = callback;
}

static pid_t record_result(pid_t result, int* status)
{
    int saved_errno = errno;
    if (observer && result > 0 && status) {
        if (WIFEXITED(*status)) observer(result, WEXITSTATUS(*status));
        else if (WIFSIGNALED(*status)) observer(result, 1);
    }
    errno = saved_errno;
    return result;
}

static pid_t observed_waitpid(pid_t pid, int* status, int options)
{
    // dyld leaves the interposing library's own call bound to the original.
    return record_result(waitpid(pid, status, options), status);
}

// .NET 10's PAL imports the non-cancelable Darwin ABI entry point.
extern "C" pid_t waitpid_nocancel(pid_t, int*, int) asm("_waitpid$NOCANCEL");
static pid_t observed_waitpid_nocancel(pid_t pid, int* status, int options)
{
    return record_result(waitpid_nocancel(pid, status, options), status);
}

__attribute__((used, section("__DATA,__interpose")))
static const struct { const void* replacement; const void* original; } interpose_waitpid = {
    reinterpret_cast<const void*>(observed_waitpid), reinterpret_cast<const void*>(waitpid)
};

__attribute__((used, section("__DATA,__interpose")))
static const struct { const void* replacement; const void* original; } interpose_waitpid_nocancel = {
    reinterpret_cast<const void*>(observed_waitpid_nocancel), reinterpret_cast<const void*>(waitpid_nocancel)
};
