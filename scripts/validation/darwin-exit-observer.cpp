// Copyright (c) 2026 vscode-csharp-autobuild contributors. MIT License.
#include "debugger/waitpid.h"
#include <sys/types.h>

extern "C" void autobuild_set_exit_observer(void (*)(pid_t, int));

static void record_exit(pid_t pid, int code)
{
    // Samsung's tracker ignores unrelated child processes and serializes updates.
    netcoredbg::GetWaitpid().SetExitCode(pid, code);
}

__attribute__((constructor)) static void register_exit_observer()
{
    autobuild_set_exit_observer(record_exit);
}
