#include <bmlib_runtime.h>
#include <features.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/time.h>
#include <time.h>
#include <unistd.h>
#define __USE_UNIX98
#include <pthread.h>

#define UNUSED(__x) (void)(__x)
#define INDEX_SHIFT(__num, __index, __shift) (__num * __index / __shift)
#define ALIGN_DOWN(__x, __y) ((__x) & ~(__y - 1))

#define MAX_MEM_DEV (16000)

static unsigned int dev_id;
static unsigned long shape[4];
static unsigned long long shape_size;
static signed long loop;
static unsigned int gdma_test_num;
static bm_handle_t bm_handle_all = NULL;
static bm_dev_stat_t dev_stat;
static unsigned int bm_dev_mem_num = 0;
static bm_device_mem_t bm_dev_mems[MAX_MEM_DEV];
static pthread_t* gdma_pid;
struct gdma_pid_arg_t {
  unsigned int id;
  unsigned int skip;
  unsigned int step;
  signed long loop;
  unsigned char* buffer_ran;
  unsigned char* buffer_sys;
  unsigned char* buffer_cmp;
};
struct gdma_pid_arg_t* gdma_pid_args;
struct rand_pid_args {
  unsigned int id;
  unsigned char* buffer_ran;
  unsigned char* buffer_sys;
  pthread_rwlock_t* rwlock;
  atomic_int* atomic_run_test_num;
};
#if USE_GDMA_WITH_CORE
static unsigned int core_num = 1;
#endif

static size_t cmp_find_error_addr(unsigned char* a, unsigned char* b,
                                  size_t size) {
  size_t ret = 0;
  for (; ret < size; ret++) {
    if (a[ret] != b[ret]) return ret;
  }
  return size;
}

static unsigned long long get_right_shape_size(unsigned long long size) {
  size = (size + ((1 * 1024 * 1024) - 1)) & ~((1 * 1024 * 1024) - 1);
  if (size > 256 * 1024 * 1024)
    return (256 * 1024 * 1024);
  else if (size < 1 * 1024 * 1024)
    return (1 * 1024 * 1024);
  else
    return size;
}

static unsigned long long get_shape_size(unsigned long* shape) {
  return get_right_shape_size(shape[0] * shape[1] * shape[2] * shape[3] * 1);
}

static void rand_buffer(unsigned char* sys_buffer, unsigned long long size) {
  for (size_t i = 0; i < size / sizeof(unsigned char); i++) {
    sys_buffer[i] = rand();
  }
}

static int parse_shape(const char* arg, unsigned long* shape) {
  const char* delimiters = "[], ";
  char* token;
  char* endptr;
  int i = 0;
  token = strtok((char*)arg, delimiters);
  while (token != NULL) {
    shape[i++] = strtol(token, &endptr, 10);
    token = strtok(NULL, delimiters);
    if (*endptr != '\0') return 0;
  }
  return i;
}

static int test_one_cmp(bm_handle_t bm_handle, bm_device_mem_t* dst,
                        bm_device_mem_t* src, unsigned char* sys_buffer,
                        unsigned char* sys_buffer2, unsigned int id,
                        unsigned char cmp_every) {
  bm_status_t bm_ret = BM_SUCCESS;
  bm_ret = bm_memcpy_d2s(bm_handle, sys_buffer2, *dst);
  if (bm_ret != BM_SUCCESS) {
    printf("[ERROR %d] bm_memcpy_d2s from 0x%lX, dev %d failed, ret: 0x%X\r\n",
           id, dst->u.device.device_addr, dev_id, bm_ret);
    exit(EXIT_FAILURE);
  }
  if (memcmp(sys_buffer, sys_buffer2, shape_size) == 0) {
    return 0;
  } else {
    size_t eaddr = cmp_find_error_addr(sys_buffer, sys_buffer2, shape_size);
    if (cmp_every == 1) {
      if (memcmp(sys_buffer, sys_buffer2, shape_size) != 0) {
        size_t eaddr = cmp_find_error_addr(sys_buffer, sys_buffer2, shape_size);
        if (src != NULL)
          printf(
              "[ERROR %d] memcmp error at offset 0x%lX: 0x%X <-> 0x%X, device "
              "mem 0x%lX->0x%lX, size 0x%llX\r\n",
              id, eaddr, sys_buffer[eaddr], sys_buffer2[eaddr],
              src->u.device.device_addr, dst->u.device.device_addr, shape_size);
        else
          printf(
              "[ERROR %d] memcmp error at offset 0x%lX: 0x%X <-> 0x%X, device "
              "mem sys->0x%lX, size 0x%llX\r\n",
              id, eaddr, sys_buffer[eaddr], sys_buffer2[eaddr],
              dst->u.device.device_addr, shape_size);
      }
    } else {
      printf("[ERROR %d] memcmp error at offset 0x%lX: 0x%X <-> 0x%X\r\n", id,
             eaddr, sys_buffer[eaddr], sys_buffer2[eaddr]);
    }
    return -1;
  }
}

static int test_one_memcp(bm_handle_t bm_handle, bm_device_mem_t* dst,
                          bm_device_mem_t* src, unsigned char* sys_buffer,
                          unsigned char* sys_buffer2, unsigned int id,
                          unsigned char cmp_every) {
  bm_status_t bm_ret = BM_SUCCESS;
#if USE_GDMA_WITH_CORE
  bm_ret = bm_memcpy_d2d_byte_with_core(bm_handle, *dst, 0, *src, 0, shape_size,
                                        id % core_num);

#else
  bm_ret = bm_memcpy_d2d_byte(bm_handle, *dst, 0, *src, 0, shape_size);
#endif
  if (bm_ret != BM_SUCCESS) {
    printf(
        "[ERROR %d] bm_memcpy_d2d_byte 0x%lX -> 0x%lX, dev %d failed, ret: "
        "0x%X\r\n",
        id, src->u.device.device_addr, dst->u.device.device_addr, dev_id,
        bm_ret);
    exit(EXIT_FAILURE);
  }
  if (cmp_every == 1) {
    bm_ret = bm_memcpy_d2s(bm_handle, sys_buffer2, *dst);
    if (bm_ret != BM_SUCCESS) {
      printf(
          "[ERROR %d] bm_memcpy_d2s from 0x%lX, dev %d failed, ret: 0x%X\r\n",
          id, dst->u.device.device_addr, dev_id, bm_ret);
      exit(EXIT_FAILURE);
    }
    if (memcmp(sys_buffer, sys_buffer2, shape_size) != 0) {
      size_t eaddr = cmp_find_error_addr(sys_buffer, sys_buffer2, shape_size);
      printf(
          "[ERROR %d] memcmp error at offset 0x%lX: 0x%X <-> 0x%X, device mem "
          "0x%lX->0x%lX, size 0x%llX\r\n",
          id, eaddr, sys_buffer[eaddr], sys_buffer2[eaddr],
          src->u.device.device_addr, dst->u.device.device_addr, shape_size);
      printf("[ERROR %d] start memory dump:");
      for (size_t offset = 0; offset < shape_size; offset += 1)
        printf("[ERROR %d] 0x%lX [SRC:0x%X] <-> [DST:0x%X]\r\n", id, offset,
               sys_buffer[offset], sys_buffer2[offset]);
      return -1;
    }
  }
  return 0;
}

static int test_one_shot(bm_handle_t bm_handle, bm_device_mem_t* dev_mem_p,
                         unsigned char* sys_buffer, unsigned char* sys_buffer2,
                         unsigned int start_index, unsigned int end_index,
                         unsigned int skip, unsigned int step, unsigned int id,
                         unsigned char cmp_every) {
  int temp_index = 0;
  bm_status_t bm_ret = BM_SUCCESS;
  if (start_index > end_index) {
    temp_index = start_index;
    start_index = end_index;
    end_index = temp_index;
  }
  start_index += skip;
  end_index = start_index + ALIGN_DOWN((end_index - start_index), step);
  if (start_index > end_index) {
    printf(
        "[ERROR %d] test_one_shot cannot find right step info, start:%d end:%d "
        "skip:%d step:%d\r\n",
        id, start_index, end_index, skip, step);
  }
  printf("[INFO %d] test one shot [0x%lX] -> [0x%lX], si%d ei%d sk%d st%d\r\n",
         id, dev_mem_p[start_index].u.device.device_addr,
         dev_mem_p[end_index].u.device.device_addr, start_index, end_index,
         skip, step);
  bm_ret = bm_memcpy_s2d(bm_handle, dev_mem_p[start_index], sys_buffer);
  if (bm_ret != BM_SUCCESS) {
    printf("[ERROR %d] bm_memcpy_s2d to 0x%lX, dev %d failed, ret: 0x%X\r\n",
           id, dev_mem_p[start_index].u.device.device_addr, dev_id, bm_ret);
    exit(EXIT_FAILURE);
  }
  if (0 != test_one_cmp(bm_handle, &dev_mem_p[start_index], NULL, sys_buffer,
                        sys_buffer2, id, cmp_every))
    return -1;
  long i = start_index;
  for (; i < end_index; i += step) {
    if (0 != test_one_memcp(bm_handle, &dev_mem_p[i + step], &dev_mem_p[i],
                            sys_buffer, sys_buffer2, id, cmp_every))
      return -1;
  }
  i -= step;
  for (; i > start_index; i -= step) {
    if (0 != test_one_memcp(bm_handle, &dev_mem_p[i - step], &dev_mem_p[i],
                            sys_buffer, sys_buffer2, id, cmp_every))
      return -1;
  }
  return test_one_cmp(bm_handle, &dev_mem_p[i], &dev_mem_p[start_index],
                      sys_buffer, sys_buffer2, id, 0);
}

static int test_two_edge(bm_handle_t bm_handle, bm_device_mem_t* dev_mem_p,
                         unsigned char* sys_buffer, unsigned char* sys_buffer2,
                         unsigned int start_index1, unsigned int end_index1,
                         unsigned int start_index2, unsigned int end_index2,
                         unsigned int skip, unsigned int step, unsigned int id,
                         unsigned char cmp_every) {
  unsigned int temp_index = 0, end_index = 0;
  bm_status_t bm_ret = BM_SUCCESS;
  if (start_index1 > end_index1) {
    temp_index = start_index1;
    start_index1 = end_index1;
    end_index1 = temp_index;
  }
  start_index1 += skip;
  end_index1 = start_index1 + ALIGN_DOWN((end_index1 - start_index1), step);
  if (start_index1 >= end_index1) {
    printf(
        "[ERROR %d] test_two_edge cannot find right step 1 info, start:%d "
        "end:%d "
        "skip:%d step:%d\r\n",
        id, start_index1, end_index1, skip, step);
    return -1;
  }
  if (start_index2 > end_index2) {
    temp_index = start_index2;
    start_index2 = end_index2;
    end_index2 = temp_index;
  }
  start_index2 += skip;
  end_index2 = start_index2 + ALIGN_DOWN((end_index2 - start_index2), step);
  if (start_index2 >= end_index2) {
    printf(
        "[ERROR %d] test_two_edge cannot find right step 2 info, start:%d "
        "end:%d "
        "skip:%d step:%d\r\n",
        id, start_index2, end_index2, skip, step);
    return -1;
  }
  unsigned int need_loop =
      (end_index1 - start_index1) > (end_index2 - start_index2)
          ? (end_index2 - start_index2)
          : (end_index1 - start_index1);
  printf(
      "[INFO %d] test two edge {[0x%lX] -> [0x%lX] [0x%lX] -> "
      "[0x%lX]}, s1i%d e1i%d s2i%d e2i%d sk%d st%d\r\n",
      id, dev_mem_p[start_index1].u.device.device_addr,
      dev_mem_p[end_index1].u.device.device_addr,
      dev_mem_p[start_index2].u.device.device_addr,
      dev_mem_p[end_index2].u.device.device_addr, start_index1, end_index1,
      start_index2, end_index2, skip, step);
  bm_ret = bm_memcpy_s2d(bm_handle, dev_mem_p[start_index1], sys_buffer);
  if (bm_ret != BM_SUCCESS) {
    printf("[ERROR %d] bm_memcpy_s2d to 0x%lX, dev %d failed, ret: 0x%X\r\n",
           id, dev_mem_p[start_index1].u.device.device_addr, dev_id, bm_ret);
    exit(EXIT_FAILURE);
  }
  if (0 != test_one_cmp(bm_handle, &dev_mem_p[start_index1], NULL, sys_buffer,
                        sys_buffer2, id, cmp_every))
    return -1;
  long i = 0;
  for (; i < need_loop; i += step) {
    if (0 != test_one_memcp(bm_handle, &dev_mem_p[start_index2 + i],
                            &dev_mem_p[start_index1 + i], sys_buffer,
                            sys_buffer2, id, cmp_every))
      return -1;
    if (0 != test_one_memcp(bm_handle, &dev_mem_p[start_index1 + i + step],
                            &dev_mem_p[start_index2 + i], sys_buffer,
                            sys_buffer2, id, cmp_every))
      return -1;
    end_index = start_index1 + i + step;
  }
  i -= step;
  for (; i > 0; i -= step) {
    if (0 != test_one_memcp(bm_handle, &dev_mem_p[start_index2 + i],
                            &dev_mem_p[start_index1 + i], sys_buffer,
                            sys_buffer2, id, cmp_every))
      return -1;
    if (0 != test_one_memcp(bm_handle, &dev_mem_p[start_index1 + i - step],
                            &dev_mem_p[start_index2 + i], sys_buffer,
                            sys_buffer2, id, cmp_every))
      return -1;
    end_index = start_index1 + i + step;
  }
  return test_one_cmp(bm_handle, &dev_mem_p[end_index],
                      &dev_mem_p[start_index1], sys_buffer, sys_buffer2, id, 0);
}

inline long long get_microseconds() {
  struct timeval tv;
  gettimeofday(&tv, NULL);
  return (long long)tv.tv_sec * 1000000 + tv.tv_usec;
}

static void print_help(int argc, char* argv[]) {
  UNUSED(argc);
  printf("[HELP] Usage: %s int \"[x, y, width, height]\" int int\n", argv[0]);
  printf("[bm dev id] [shape size] [loop num] [test thread num]\n");
  printf("[bm dev id] 运行测试的设备ID\n");
  printf(
      "[shape size] "
      "测试数据的size,里面的数字会乘积运算后为单次搬运数据量,例如[1,3,1920,"
      "1080]\n");
  printf("[loop num] 传输测试环回次数\n");
  printf("[test thread num] GDMA测试线程\n");
}

static void* ran_buffer_thread(void* arg) {
  struct rand_pid_args* args = (struct rand_pid_args*)arg;
  while (atomic_load(args->atomic_run_test_num) != 0) {
    rand_buffer(args->buffer_ran, shape_size);
    pthread_rwlock_wrlock(args->rwlock);
    memcpy(args->buffer_sys, args->buffer_ran, shape_size);
    pthread_rwlock_unlock(args->rwlock);
    sleep(1);
  }
  return NULL;
}

static void* test_gdma_ddr_thread(void* arg) {
  struct gdma_pid_arg_t* args = (struct gdma_pid_arg_t*)arg;
  atomic_int atomic_run_test_num = 0;
  pthread_rwlock_t rwlock;
  pthread_t rand_pid;
  bm_handle_t bm_handle;
  atomic_fetch_add(&atomic_run_test_num, 1);
  printf("[INFO %d] GDMA test thread start, skip: %d, step: %d\r\n", args->id,
         args->skip, args->step);
  if (BM_SUCCESS != bm_dev_request(&bm_handle, dev_id)) {
    printf("[ERROR] request dev %d failed\n", dev_id);
    exit(EXIT_FAILURE);
  }
  pthread_rwlock_init(&rwlock, NULL);
  struct rand_pid_args rand_args = {
      .id = args->id,
      .atomic_run_test_num = &atomic_run_test_num,
      .buffer_ran = args->buffer_ran,
      .buffer_sys = args->buffer_sys,
      .rwlock = &rwlock,
  };
  if (pthread_create(&rand_pid, NULL, ran_buffer_thread, &rand_args)) {
    printf("[ERROR %d] create RAND thread failed\r\n", args->id);
    exit(EXIT_FAILURE);
  }
  while (1) {
    if (args->loop > 0) {
      printf("[INFO %d] need run loop num: %ld\r\n", args->id, args->loop);
      args->loop--;
    } else if (args->loop == 0)
      break;
    pthread_rwlock_rdlock(&rwlock);
    if (test_one_shot(bm_handle, bm_dev_mems, args->buffer_sys,
                      args->buffer_cmp, 0, bm_dev_mem_num - 1, args->skip,
                      args->step, args->id, 0) != 0) {
      printf("[PANIC %d] test_one_shot error, restart one loop cmp every..\n",
             args->id);
      test_one_shot(bm_handle, bm_dev_mems, args->buffer_sys, args->buffer_cmp,
                    0, bm_dev_mem_num - 1, args->skip, args->step, args->id, 1);
      printf("[PANIC %d] test_one_shot error\r\n", args->id);
      exit(EXIT_FAILURE);
    }
    pthread_rwlock_unlock(&rwlock);
    pthread_rwlock_rdlock(&rwlock);
    if (test_two_edge(
            bm_handle, bm_dev_mems, args->buffer_sys, args->buffer_cmp,
            ALIGN_DOWN(INDEX_SHIFT((bm_dev_mem_num - 1), 0, 4), args->step),
            INDEX_SHIFT((bm_dev_mem_num - 1), 1, 4),
            ALIGN_DOWN(INDEX_SHIFT((bm_dev_mem_num - 1), 1, 4), args->step),
            INDEX_SHIFT((bm_dev_mem_num - 1), 2, 4), args->skip, args->step,
            args->id, 0) != 0) {
      printf(
          "[PANIC %d] test_two_edge error, restart one loop cmp every...\r\n",
          args->id);
      test_two_edge(
          bm_handle, bm_dev_mems, args->buffer_sys, args->buffer_cmp,
          ALIGN_DOWN(INDEX_SHIFT((bm_dev_mem_num - 1), 0, 4), args->step),
          INDEX_SHIFT((bm_dev_mem_num - 1), 1, 4),
          ALIGN_DOWN(INDEX_SHIFT((bm_dev_mem_num - 1), 1, 4), args->step),
          INDEX_SHIFT((bm_dev_mem_num - 1), 2, 4), args->skip, args->step,
          args->id, 1);
      printf("[PANIC %d] test_two_edge error\r\n", args->id);
      exit(EXIT_FAILURE);
    }
    pthread_rwlock_unlock(&rwlock);
    pthread_rwlock_rdlock(&rwlock);
    if (test_two_edge(
            bm_handle, bm_dev_mems, args->buffer_sys, args->buffer_cmp,
            ALIGN_DOWN(INDEX_SHIFT((bm_dev_mem_num - 1), 0, 4), args->step),
            INDEX_SHIFT((bm_dev_mem_num - 1), 1, 4),
            ALIGN_DOWN(INDEX_SHIFT((bm_dev_mem_num - 1), 2, 4), args->step),
            INDEX_SHIFT((bm_dev_mem_num - 1), 3, 4), args->skip, args->step,
            args->id, 0) != 0) {
      printf(
          "[PANIC %d] test_two_edge error, restart one loop cmp every...\r\n",
          args->id);
      test_two_edge(
          bm_handle, bm_dev_mems, args->buffer_sys, args->buffer_cmp,
          ALIGN_DOWN(INDEX_SHIFT((bm_dev_mem_num - 1), 0, 4), args->step),
          INDEX_SHIFT((bm_dev_mem_num - 1), 1, 4),
          ALIGN_DOWN(INDEX_SHIFT((bm_dev_mem_num - 1), 2, 4), args->step),
          INDEX_SHIFT((bm_dev_mem_num - 1), 3, 4), args->skip, args->step,
          args->id, 1);
      printf("[PANIC %d] test_two_edge error\r\n", args->id);
      exit(EXIT_FAILURE);
    }
    pthread_rwlock_unlock(&rwlock);
    pthread_rwlock_rdlock(&rwlock);
    if (test_two_edge(
            bm_handle, bm_dev_mems, args->buffer_sys, args->buffer_cmp,
            ALIGN_DOWN(INDEX_SHIFT((bm_dev_mem_num - 1), 0, 4), args->step),
            INDEX_SHIFT((bm_dev_mem_num - 1), 1, 4),
            ALIGN_DOWN(INDEX_SHIFT((bm_dev_mem_num - 1), 3, 4), args->step),
            INDEX_SHIFT((bm_dev_mem_num - 1), 4, 4), args->skip, args->step,
            args->id, 0) != 0) {
      printf(
          "[PANIC %d] test_two_edge error, restart one loop cmp every...\r\n",
          args->id);
      test_two_edge(
          bm_handle, bm_dev_mems, args->buffer_sys, args->buffer_cmp,
          ALIGN_DOWN(INDEX_SHIFT((bm_dev_mem_num - 1), 0, 4), args->step),
          INDEX_SHIFT((bm_dev_mem_num - 1), 1, 4),
          ALIGN_DOWN(INDEX_SHIFT((bm_dev_mem_num - 1), 3, 4), args->step),
          INDEX_SHIFT((bm_dev_mem_num - 1), 4, 4), args->skip, args->step,
          args->id, 1);
      printf("[PANIC %d] test_two_edge error\r\n", args->id);
      exit(EXIT_FAILURE);
    }
    pthread_rwlock_unlock(&rwlock);
    pthread_rwlock_rdlock(&rwlock);
    if (test_two_edge(
            bm_handle, bm_dev_mems, args->buffer_sys, args->buffer_cmp,
            ALIGN_DOWN(INDEX_SHIFT((bm_dev_mem_num - 1), 1, 4), args->step),
            INDEX_SHIFT((bm_dev_mem_num - 1), 2, 4),
            ALIGN_DOWN(INDEX_SHIFT((bm_dev_mem_num - 1), 2, 4), args->step),
            INDEX_SHIFT((bm_dev_mem_num - 1), 3, 4), args->skip, args->step,
            args->id, 0) != 0) {
      printf(
          "[PANIC %d] test_two_edge error, restart one loop cmp every...\r\n",
          args->id);
      test_two_edge(
          bm_handle, bm_dev_mems, args->buffer_sys, args->buffer_cmp,
          ALIGN_DOWN(INDEX_SHIFT((bm_dev_mem_num - 1), 1, 4), args->step),
          INDEX_SHIFT((bm_dev_mem_num - 1), 2, 4),
          ALIGN_DOWN(INDEX_SHIFT((bm_dev_mem_num - 1), 2, 4), args->step),
          INDEX_SHIFT((bm_dev_mem_num - 1), 3, 4), args->skip, args->step,
          args->id, 1);
      printf("[PANIC %d] test_two_edge error\r\n", args->id);
      exit(EXIT_FAILURE);
    }
    pthread_rwlock_unlock(&rwlock);
    pthread_rwlock_rdlock(&rwlock);
    if (test_two_edge(
            bm_handle, bm_dev_mems, args->buffer_sys, args->buffer_cmp,
            ALIGN_DOWN(INDEX_SHIFT((bm_dev_mem_num - 1), 1, 4), args->step),
            INDEX_SHIFT((bm_dev_mem_num - 1), 2, 4),
            ALIGN_DOWN(INDEX_SHIFT((bm_dev_mem_num - 1), 3, 4), args->step),
            INDEX_SHIFT((bm_dev_mem_num - 1), 4, 4), args->skip, args->step,
            args->id, 0) != 0) {
      printf(
          "[PANIC %d] test_two_edge error, restart one loop cmp every...\r\n",
          args->id);
      test_two_edge(
          bm_handle, bm_dev_mems, args->buffer_sys, args->buffer_cmp,
          ALIGN_DOWN(INDEX_SHIFT((bm_dev_mem_num - 1), 1, 4), args->step),
          INDEX_SHIFT((bm_dev_mem_num - 1), 2, 4),
          ALIGN_DOWN(INDEX_SHIFT((bm_dev_mem_num - 1), 3, 4), args->step),
          INDEX_SHIFT((bm_dev_mem_num - 1), 4, 4), args->skip, args->step,
          args->id, 1);
      printf("[PANIC %d] test_two_edge error\r\n", args->id);
      exit(EXIT_FAILURE);
    }
    pthread_rwlock_unlock(&rwlock);
    pthread_rwlock_rdlock(&rwlock);
    if (test_two_edge(
            bm_handle, bm_dev_mems, args->buffer_sys, args->buffer_cmp,
            ALIGN_DOWN(INDEX_SHIFT((bm_dev_mem_num - 1), 2, 4), args->step),
            INDEX_SHIFT((bm_dev_mem_num - 1), 3, 4),
            ALIGN_DOWN(INDEX_SHIFT((bm_dev_mem_num - 1), 3, 4), args->step),
            INDEX_SHIFT((bm_dev_mem_num - 1), 4, 4), args->skip, args->step,
            args->id, 0) != 0) {
      printf(
          "[PANIC %d] test_two_edge error, restart one loop cmp every...\r\n",
          args->id);
      test_two_edge(
          bm_handle, bm_dev_mems, args->buffer_sys, args->buffer_cmp,
          ALIGN_DOWN(INDEX_SHIFT((bm_dev_mem_num - 1), 2, 4), args->step),
          INDEX_SHIFT((bm_dev_mem_num - 1), 3, 4),
          ALIGN_DOWN(INDEX_SHIFT((bm_dev_mem_num - 1), 3, 4), args->step),
          INDEX_SHIFT((bm_dev_mem_num - 1), 4, 4), args->skip, args->step,
          args->id, 1);
      printf("[PANIC %d] test_two_edge error\r\n", args->id);
      exit(EXIT_FAILURE);
    }
    pthread_rwlock_unlock(&rwlock);
  }
  atomic_fetch_sub(&atomic_run_test_num, 1);
  pthread_join(rand_pid, NULL);
  pthread_rwlock_destroy(&rwlock);
  bm_dev_free(bm_handle);
  printf("[INFO %d] GDMA test thread end\r\n", args->id);
  return NULL;
}

int main(int argc, char* argv[]) {
  char* endptr;
  if (argc != 5) {
    print_help(argc, argv);
    exit(EXIT_FAILURE);
  }
  dev_id = atoi(argv[1]);
  printf("[INFO] use device id: %d\r\n", dev_id);
  if (parse_shape(argv[2], shape) != 4) {
    printf("[ERROR] Invalid shape format.\r\n");
    print_help(argc, argv);
    exit(EXIT_FAILURE);
  }
  shape_size = get_shape_size(shape);
  printf("[INFO] use shape info: [%ld, %ld, %ld, %ld], size: %lld B\r\n",
         shape[0], shape[1], shape[2], shape[3], shape_size);
  loop = strtol(argv[3], &endptr, 10);
  if (*endptr != '\0') {
    printf("[ERROR] Invalid loop num format.\r\n");
    print_help(argc, argv);
    exit(EXIT_FAILURE);
  }
  printf("[INFO] use loop num: %ld\r\n", loop);
  gdma_test_num = strtol(argv[4], &endptr, 10);
  if (*endptr != '\0') {
    printf("[ERROR] Invalid two gdma format.\r\n");
    print_help(argc, argv);
    exit(EXIT_FAILURE);
  }

  if (BM_SUCCESS != bm_dev_request(&bm_handle_all, dev_id)) {
    printf("[ERROR] request dev %d failed\n", dev_id);
    exit(EXIT_FAILURE);
  }
  if (bm_get_stat(bm_handle_all, &dev_stat) != BM_SUCCESS) {
    printf("[ERROR] get heap stat fail dev %d failed\n", dev_id);
    exit(EXIT_FAILURE);
  }
  printf("[INFO] dev mem total: %d MiB, heap num: %d\r\n", dev_stat.mem_total,
         dev_stat.heap_num);
#if USE_GDMA_WITH_CORE
  if (bm_get_tpu_scalar_num(bm_handle_all, &core_num) != BM_SUCCESS) {
    printf("[ERROR] get core num dev %d failed\n", dev_id);
    exit(EXIT_FAILURE);
  }
  printf("[INFO] core num: %d\r\n", core_num);
#endif
  for (int i = 0; i < dev_stat.heap_num; i++) {
    bm_heap_stat_byte_t bm_mem_stat;
    if (bm_get_gmem_heap_stat_byte_by_id(bm_handle_all, &bm_mem_stat, i) !=
        BM_SUCCESS) {
      printf("[ERROR] bm_get_gmem_heap_stat_byte_by_id dev %d failed\n",
             dev_id);
      exit(EXIT_FAILURE);
    }
    printf(
        "[INFO] heap %d, mem total: %lld B, mem used: %lld B, mem avail: %lld "
        "B\r\n",
        i, bm_mem_stat.mem_total, bm_mem_stat.mem_used, bm_mem_stat.mem_avail);
    if ((bm_mem_stat.mem_used != 0) ||
        (bm_mem_stat.mem_total != bm_mem_stat.mem_avail)) {
      printf("[ERROR] dev %d heap %d not 0 use\r\n", dev_id, i);
    }
    unsigned long long alloc_num =
        (bm_mem_stat.mem_avail - 0x300000) / shape_size;
    for (unsigned long long k = 0; k < alloc_num; k++) {
      bm_device_mem_t* dev_mem = &bm_dev_mems[bm_dev_mem_num++];
      if (bm_malloc_device_byte_heap(bm_handle_all, dev_mem, i, shape_size) !=
          BM_SUCCESS) {
        printf("[ERROR] bm_get_gmem_heap_stat_byte_by_id dev %d failed\n",
               dev_id);
        exit(EXIT_FAILURE);
      }
      printf("[INFO] alloc dev mem start: 0x%lX\r\n",
             dev_mem->u.device.device_addr);
    }
  }
  printf("[INFO] alloc dev mem loop num: %d\r\n", bm_dev_mem_num);

  printf("[INFO] use gdma test num: %d\r\n", gdma_test_num);
  gdma_pid = malloc(sizeof(pthread_t) * gdma_test_num);
  if (gdma_pid == NULL) {
    printf("[ERROR] malloc gdma_pid failed, size: %lld\r\n", shape_size);
    return 1;
  }
  gdma_pid_args = malloc(sizeof(struct gdma_pid_arg_t) * gdma_test_num);
  if (gdma_pid_args == NULL) {
    printf("[ERROR] malloc gdma_pid_args failed, size: %lld\r\n", shape_size);
    return 1;
  }
  for (unsigned int i = 0; i < gdma_test_num; i++) {
    unsigned char* sys_buffer = malloc(shape_size);
    if (sys_buffer == NULL) {
      printf("[ERROR] malloc sys_buffer failed, size: %lld\r\n", shape_size);
      return 1;
    }
    unsigned char* cmp_buffer = malloc(shape_size);
    if (sys_buffer == NULL) {
      printf("[ERROR] malloc cmp_buffer failed, size: %lld\r\n", shape_size);
      return 1;
    }
    unsigned char* ran_buffer = malloc(shape_size);
    if (sys_buffer == NULL) {
      printf("[ERROR] malloc ran_buffer failed, size: %lld\r\n", shape_size);
      return 1;
    }
    rand_buffer(sys_buffer, shape_size);
    pthread_rwlock_t* rwlock = malloc(sizeof(pthread_rwlock_t));
    pthread_rwlock_init(rwlock, NULL);
    gdma_pid_args[i].id = i;
    gdma_pid_args[i].skip = i;
    gdma_pid_args[i].step = gdma_test_num;
    gdma_pid_args[i].loop = loop;
    gdma_pid_args[i].buffer_sys = sys_buffer;
    gdma_pid_args[i].buffer_cmp = cmp_buffer;
    gdma_pid_args[i].buffer_ran = ran_buffer;
  }
  for (unsigned int i = 0; i < gdma_test_num; i++) {
    if (pthread_create(&(gdma_pid[i]), NULL, test_gdma_ddr_thread,
                       &(gdma_pid_args[i]))) {
      printf("[ERROR] create GDMA thread failed\n");
      exit(EXIT_FAILURE);
    }
  }
  for (unsigned int i = 0; i < gdma_test_num; i++) {
    pthread_join(gdma_pid[i], NULL);
    free(gdma_pid_args[i].buffer_sys);
    free(gdma_pid_args[i].buffer_cmp);
    free(gdma_pid_args[i].buffer_ran);
  }
  for (unsigned int i = 1; i < bm_dev_mem_num; i++) {
    bm_free_device(bm_handle_all, bm_dev_mems[i]);
  }
  bm_dev_free(bm_handle_all);
  bm_handle_all = NULL;
  return 0;
}
