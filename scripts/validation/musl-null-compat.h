// Build-time compatibility for Samsung's integer metadata-token casts of NULL.
// musl uses nullptr in C++11; use Clang's GNU null constant, as glibc does.
// This header is external to the original Samsung source tree.
#ifdef __cplusplus
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wchar.h>
#include <time.h>
#include <unistd.h>
#include <locale.h>
#undef NULL
#define NULL __null
#endif
