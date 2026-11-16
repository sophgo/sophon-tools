/* LD_PRELOAD profiler for the CV84X6 decode loop.
 *
 * Interposes the bmrt/bmlib calls the engine makes and records, per call, the
 * *CPU* time the call itself took (the submit side) separately from the time
 * bm_thread_sync then waited (the TPU side). The engine is untouched, so the
 * numbers describe the shipped library exactly.
 *
 *   BM_PROF=1            enable (protects against cost in production runs)
 *   BM_PROF_OUT=path     JSON summary at exit (default: stderr)
 *   BM_PROF_CALLS=path   per-call CSV: seq,kind,name,cpu_us,bytes
 *
 * Build on the board:
 *   gcc -O2 -fPIC -shared -I/opt/sophon/libsophon-current/include \
 *       -o bmprof.so bmprof.c -ldl
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "bmruntime_interface.h"
#include "bmlib_runtime.h"

#define MAX_NETS 256
#define MAX_NAME 64

typedef struct {
  char name[MAX_NAME];
  unsigned long long calls;
  double cpu_us;
} net_stat_t;

static net_stat_t g_nets[MAX_NETS];
static int g_nnet;
static double g_launch_us, g_sync_us, g_s2d_us, g_d2s_us, g_d2d_us, g_memset_us;
static unsigned long long g_launch_calls, g_sync_calls;
static unsigned long long g_s2d_bytes, g_d2s_bytes, g_d2d_bytes;
static unsigned long long g_memset_calls, g_memset_bytes;
static double g_first_us, g_last_us;
static FILE* g_calls;
static int g_on = -1;

static double now_us(void) {
  struct timespec ts;
  clock_gettime(CLOCK_MONOTONIC, &ts);
  return ts.tv_sec * 1e6 + ts.tv_nsec / 1e3;
}

/* libsophon is loaded RTLD_LOCAL (ctypes dlopens the engine .so with the
 * default mode), so RTLD_NEXT from a preload object cannot see its symbols.
 * dlopen the two libraries by soname instead: for an already-loaded object the
 * same handle comes back, and RTLD_GLOBAL puts it in the scope dlsym searches.
 * RTLD_NEXT stays as the fallback for a statically linked probe binary. */
static void* sym(const char* name) {
  static void* bmrt;
  static void* bmlib;
  void* p = NULL;
  if (!bmrt) bmrt = dlopen("libbmrt.so", RTLD_LAZY | RTLD_GLOBAL);
  if (!bmlib) bmlib = dlopen("libbmlib.so", RTLD_LAZY | RTLD_GLOBAL);
  if (bmrt) p = dlsym(bmrt, name);
  if (!p && bmlib) p = dlsym(bmlib, name);
  if (!p) p = dlsym(RTLD_NEXT, name);
  return p;
}

static int enabled(void) {
  if (g_on < 0) {
    g_on = getenv("BM_PROF") != NULL;
    if (g_on) {
      const char* p = getenv("BM_PROF_CALLS");
      if (p) g_calls = fopen(p, "w");
      g_first_us = now_us();
      if (g_calls) fprintf(g_calls, "seq,kind,name,cpu_us,bytes,t_start_us\n");
    }
  }
  return g_on;
}

static net_stat_t* stat_for(const char* name) {
  for (int i = 0; i < g_nnet; i++)
    if (strcmp(g_nets[i].name, name) == 0) return &g_nets[i];
  if (g_nnet >= MAX_NETS) return &g_nets[0];
  net_stat_t* s = &g_nets[g_nnet++];
  snprintf(s->name, MAX_NAME, "%s", name ? name : "?");
  return s;
}

static void dump(void) {
  if (!g_launch_calls) return;
  g_last_us = now_us();
  const char* out = getenv("BM_PROF_OUT");
  FILE* f = out ? fopen(out, "w") : stderr;
  if (!f) f = stderr;
  fprintf(f, "{\n \"wall_s\": %.3f,\n \"launch_calls\": %llu, \"launch_cpu_ms\": %.2f,\n"
             " \"sync_calls\": %llu, \"sync_wait_ms\": %.2f,\n"
             " \"s2d_bytes\": %llu, \"s2d_ms\": %.2f,\n"
             " \"d2s_bytes\": %llu, \"d2s_ms\": %.2f,\n"
             " \"d2d_bytes\": %llu, \"d2d_ms\": %.2f,\n"
             " \"memset_calls\": %llu, \"memset_bytes\": %llu, \"memset_ms\": %.2f,\n \"nets\": [",
          (g_last_us - g_first_us) / 1e6, g_launch_calls, g_launch_us / 1e3,
          g_sync_calls, g_sync_us / 1e3, g_s2d_bytes, g_s2d_us / 1e3,
          g_d2s_bytes, g_d2s_us / 1e3, g_d2d_bytes, g_d2d_us / 1e3,
          g_memset_calls, g_memset_bytes, g_memset_us / 1e3);
  for (int i = 0; i < g_nnet; i++)
    fprintf(f, "%s\n  {\"name\": \"%s\", \"calls\": %llu, \"cpu_ms\": %.2f}",
            i ? "," : "", g_nets[i].name, g_nets[i].calls, g_nets[i].cpu_us / 1e3);
  fprintf(f, "\n ]\n}\n");
  if (f != stderr) fclose(f);
}

__attribute__((constructor)) static void init(void) { atexit(dump); }

bool bmrt_launch_tensor_ex(void* p_bmrt, const char* net_name,
                           const bm_tensor_t* in_tensors, int in_num,
                           bm_tensor_t* out_tensors, int out_num,
                           bool user_mem, bool user_stmode) {
  typedef bool (*fn_t)(void*, const char*, const bm_tensor_t*, int, bm_tensor_t*,
                       int, bool, bool);
  static fn_t real;
  if (!real) real = (fn_t)sym("bmrt_launch_tensor_ex");
  if (!enabled()) return real(p_bmrt, net_name, in_tensors, in_num, out_tensors,
                              out_num, user_mem, user_stmode);
  double t0 = now_us();
  bool r = real(p_bmrt, net_name, in_tensors, in_num, out_tensors, out_num,
                user_mem, user_stmode);
  double dt = now_us() - t0;
  net_stat_t* s = stat_for(net_name);
  s->calls++;
  s->cpu_us += dt;
  g_launch_calls++;
  g_launch_us += dt;
  if (g_calls) fprintf(g_calls, "%llu,launch,%s,%.1f,0,%.1f\n", g_launch_calls, net_name, dt, t0 - g_first_us);
  return r;
}

bm_status_t bm_thread_sync(bm_handle_t handle) {
  typedef bm_status_t (*fn_t)(bm_handle_t);
  static fn_t real;
  if (!real) real = (fn_t)sym("bm_thread_sync");
  if (!enabled()) return real(handle);
  double t0 = now_us();
  bm_status_t r = real(handle);
  double dt = now_us() - t0;
  g_sync_calls++;
  g_sync_us += dt;
  if (g_calls) fprintf(g_calls, "%llu,sync,-,%.1f,0,%.1f\n", g_launch_calls, dt, t0 - g_first_us);
  return r;
}

bm_status_t bm_memcpy_s2d(bm_handle_t h, bm_device_mem_t dst, void* src) {
  typedef bm_status_t (*fn_t)(bm_handle_t, bm_device_mem_t, void*);
  static fn_t real;
  if (!real) real = (fn_t)sym("bm_memcpy_s2d");
  if (!enabled()) return real(h, dst, src);
  double t0 = now_us(); bm_status_t r = real(h, dst, src);
  double dt = now_us() - t0;
  unsigned int n = bm_mem_get_device_size(dst);
  g_s2d_us += dt; g_s2d_bytes += n;
  if (g_calls) fprintf(g_calls, "%llu,s2d,-,%.1f,%u,%.1f\n", g_launch_calls, dt, n, t0 - g_first_us);
  return r;
}

bm_status_t bm_memcpy_s2d_partial(bm_handle_t h, bm_device_mem_t dst, void* src,
                                  unsigned int n) {
  typedef bm_status_t (*fn_t)(bm_handle_t, bm_device_mem_t, void*, unsigned int);
  static fn_t real;
  if (!real) real = (fn_t)sym("bm_memcpy_s2d_partial");
  if (!enabled()) return real(h, dst, src, n);
  double t0 = now_us(); bm_status_t r = real(h, dst, src, n);
  double dt = now_us() - t0;
  g_s2d_us += dt; g_s2d_bytes += n;
  if (g_calls) fprintf(g_calls, "%llu,s2d,-,%.1f,%u,%.1f\n", g_launch_calls, dt, n, t0 - g_first_us);
  return r;
}

bm_status_t bm_memcpy_d2s_partial(bm_handle_t h, void* dst, bm_device_mem_t src,
                                  unsigned int n) {
  typedef bm_status_t (*fn_t)(bm_handle_t, void*, bm_device_mem_t, unsigned int);
  static fn_t real;
  if (!real) real = (fn_t)sym("bm_memcpy_d2s_partial");
  if (!enabled()) return real(h, dst, src, n);
  double t0 = now_us(); bm_status_t r = real(h, dst, src, n);
  double dt = now_us() - t0;
  g_d2s_us += dt; g_d2s_bytes += n;
  if (g_calls) fprintf(g_calls, "%llu,d2s,-,%.1f,%u,%.1f\n", g_launch_calls, dt, n, t0 - g_first_us);
  return r;
}

bm_status_t bm_memcpy_d2d_byte(bm_handle_t h, bm_device_mem_t dst, size_t doff,
                               bm_device_mem_t src, size_t soff, size_t n) {
  typedef bm_status_t (*fn_t)(bm_handle_t, bm_device_mem_t, size_t, bm_device_mem_t,
                              size_t, size_t);
  static fn_t real;
  if (!real) real = (fn_t)sym("bm_memcpy_d2d_byte");
  if (!enabled()) return real(h, dst, doff, src, soff, n);
  double t0 = now_us(); bm_status_t r = real(h, dst, doff, src, soff, n);
  double dt = now_us() - t0;
  g_d2d_us += dt; g_d2d_bytes += n;
  if (g_calls) fprintf(g_calls, "%llu,d2d,-,%.1f,%zu,%.1f\n", g_launch_calls, dt, n, t0 - g_first_us);
  return r;
}

bm_status_t bm_memset_device_ext(bm_handle_t h, void* v, int mode, bm_device_mem_t mem) {
  typedef bm_status_t (*fn_t)(bm_handle_t, void*, int, bm_device_mem_t);
  static fn_t real;
  if (!real) real = (fn_t)sym("bm_memset_device_ext");
  if (!enabled()) return real(h, v, mode, mem);
  double t0 = now_us(); bm_status_t r = real(h, v, mode, mem);
  const double dt = now_us() - t0;
  g_memset_us += dt;
  g_memset_calls++;
  g_memset_bytes += bm_mem_get_device_size(mem);
  if (g_calls) fprintf(g_calls, "%llu,memset,-,%.1f,%u,%.1f\n", g_launch_calls, dt,
                       bm_mem_get_device_size(mem), t0 - g_first_us);
  return r;
}
