// SPDX-License-Identifier: MIT
// Repository-owned experimental hosting compatibility for musl.
// See https://github.com/dotnet/runtime/issues/103741.
// Link wrapping affects dlsym references in this executable, not its shared libraries.
#include <atomic>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <pthread.h>

namespace {
using Initialize = int (*)(const char *, const char *, int, const char **,
                          const char **, void **, unsigned int *);
std::atomic<Initialize> initialize{nullptr};
constexpr int failure = static_cast<int>(0x80004005u);

struct Invocation {
    Initialize function;
    const char *exe;
    const char *name;
    int count;
    const char **keys;
    const char **values;
    void **host;
    unsigned int *domain;
    int result;
};

void *run(void *state)
{
    auto &call = *static_cast<Invocation *>(state);
    call.result = call.function(call.exe, call.name, call.count, call.keys,
                                call.values, call.host, call.domain);
    return nullptr;
}

int initialize_on_owned_stack(const char *exe, const char *name, int count,
                              const char **keys, const char **values,
                              void **host, unsigned int *domain)
{
    Invocation call{initialize.load(), exe, name, count, keys, values, host, domain, failure};
    if (!call.function)
        return failure;
    // CoreCLR probes 1.5 MiB on its initializing thread with the tested musl runtimes.
    // DBI's callback thread has only that much total stack. Reserve headroom on an
    // owned thread instead of changing process-wide CLR configuration.
    pthread_attr_t attributes;
    if (pthread_attr_init(&attributes) != 0)
        return failure;
    int error = pthread_attr_setstacksize(&attributes, 8u * 1024u * 1024u);
    pthread_t thread;
    if (error == 0)
        error = pthread_create(&thread, &attributes, run, &call);
    pthread_attr_destroy(&attributes);
    if (error != 0)
        return failure;
    // Keep the caller's arguments and result slots alive until initialization ends.
    // A join failure cannot safely return while the worker may still use them.
    if (pthread_join(thread, nullptr) != 0)
        std::abort();
    std::fprintf(stderr, "netcoredbg musl host: CoreCLR initialized on owned 8 MiB stack, status=%d\n", call.result);
    return call.result;
}
} // namespace

extern "C" void *__real_dlsym(void *, const char *);
extern "C" void *__wrap_dlsym(void *handle, const char *name)
{
    void *symbol = __real_dlsym(handle, name);
    if (!symbol || std::strcmp(name, "coreclr_initialize") != 0)
        return symbol;
    auto function = reinterpret_cast<Initialize>(symbol);
    Initialize expected = nullptr;
    if (!initialize.compare_exchange_strong(expected, function) && expected != function)
        return nullptr; // Hosting multiple CoreCLR instances is outside this adapter's contract.
    return reinterpret_cast<void *>(&initialize_on_owned_stack);
}
