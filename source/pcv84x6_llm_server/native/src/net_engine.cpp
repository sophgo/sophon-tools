// The generic single-graph runner behind cv_net_*. See net_engine.h for why it
// exists and what it refuses to do.
//
// The launch discipline is the same as the other engines': bmrt_launch_tensor_ex
// over the graph's own stage-0 memories, a sync before reading anything back,
// and buffers that are the graph's (so a rebuild with different shapes needs no
// change here). What differs is that no name is looked up: a one-graph bmodel
// has exactly one network and its name is whatever the compiler chose.

#include "net_engine.h"

#include "aux_common.h"
#include "bmruntime_interface.h"
#include "bmlib_runtime.h"

#include <cstdio>
#include <cstring>
#include <mutex>
#include <stdexcept>
#include <string>
#include <vector>

namespace cv84x6 {

namespace {

// Same NPU heap mask the other engines use: only buffers allocated from the NPU
// heap may be handed to the driver.
constexpr int kNpuHeapMask = 3;

// One host<->device element, in whichever direction the dtype requires.
// float32 is a straight copy; the three 16-bit types go through the same
// conversions aux_common.h already uses (which include the fp16 denormal
// branch a naive bit shift gets wrong).
inline float read_element(const void* base, long long i, bm_data_type_t dtype) {
  switch (dtype) {
    case BM_FLOAT32:
      return static_cast<const float*>(base)[i];
    case BM_FLOAT16:
      return aux::fp16_to_f32(static_cast<const uint16_t*>(base)[i]);
    case BM_BFLOAT16:
      return aux::bf16_to_f32(static_cast<const uint16_t*>(base)[i]);
    default:
      return 0.0f;
  }
}

inline void write_element(void* base, long long i, float v, bm_data_type_t dtype) {
  switch (dtype) {
    case BM_FLOAT32:
      static_cast<float*>(base)[i] = v;
      break;
    case BM_FLOAT16:
      static_cast<uint16_t*>(base)[i] = aux::float_to_fp16(v);
      break;
    case BM_BFLOAT16: {
      // Truncation, matching aux::f32_to_bf16: the reference demo takes the
      // upper half rather than rounding, and a rebuild that compares against
      // that demo must not differ by a rounding step.
      //
      // memcpy rather than a reinterpret_cast of &v: type-punning a float
      // through a uint32_t pointer is undefined by the C++ aliasing rules, and
      // gcc says so at -Wall. It happens to work on this target, which is
      // exactly why it must not stay.
      uint32_t bits;
      std::memcpy(&bits, &v, sizeof(bits));
      static_cast<uint16_t*>(base)[i] = static_cast<uint16_t>(bits >> 16);
      break;
    }
    default:
      break;
  }
}

}  // namespace

struct NetEngine::Impl {
  bm_handle_t handle = nullptr;
  void* bmrt = nullptr;
  std::mutex mu;  // one NPU: launches are serialised
  std::string last_error;

  const bm_net_info_t* net = nullptr;
  int num_stages = 1;

  //: True when the bmodel addresses its I/O by tag rather than by real memory
  //: (``ADDR_MODE_IO_TAG``/``_FUSE``, which is what tpu-mlir emits for a plain
  //: single graph). The graph's own ``input_mems``/``output_mems`` are then
  //: *placeholders* at synthetic addresses like ``0x40000000000`` that no copy
  //: can reach -- ``bm_memcpy_s2d`` rejects them with "out of range", which is
  //: exactly what the first board run of this engine hit. Such a graph needs
  //: caller-owned tensors (``bmrt_tensor_ex``), the same thing ``bmrt_test``
  //: does for every bmodel it runs. See ``load`` for where this is decided and
  //: the chat builds for the other case (they set ADDR_MODE_IO_ALONE/BASIC and
  //: *do* own their buffers).
  bool tagged_io = false;
  //: One device buffer per tensor, in tag mode only. Owned here and freed in
  //: the destructor.
  std::vector<bm_device_mem_t> input_mem;
  std::vector<bm_device_mem_t> output_mem;

  // Scratch for the d2s copy, sized at load from the largest output. Reused
  // across calls: one worker serves many requests and this is a per-image
  // buffer, not a per-graph one.
  std::vector<uint8_t> host_out;
  // Scratch for a converted input, likewise reused.
  std::vector<uint8_t> host_in;

  bool fail(const std::string& msg) {
    last_error = msg;
    return false;
  }

  static long long elements(const bm_shape_t& shape) {
    long long n = 1;
    for (int i = 0; i < shape.num_dims; i++) n *= shape.dims[i];
    return n;
  }

  int dtype_bytes(bm_data_type_t t) const {
    switch (t) {
      case BM_FLOAT32:
      case BM_INT32:
      case BM_UINT32:
        return 4;
      case BM_FLOAT16:
      case BM_BFLOAT16:
      case BM_INT16:
      case BM_UINT16:
        return 2;
      case BM_INT8:
      case BM_UINT8:
        return 1;
      default:
        return 4;
    }
  }

  // The device memory a tensor of this graph actually occupies: the graph's own
  // slot in the non-tagged case, our allocation in the tagged one.
  //
  // Only stage 0 is ever handed out. These bmodels are single-stage (a plain
  // static CNN is by construction), and a multi-stage graph would need one
  // allocation per stage rather than one per tensor -- a shape this engine does
  // not claim to serve, which `load` rejects rather than mis-sizes.
  bm_device_mem_t in_mem(int i) const {
    return tagged_io ? input_mem[static_cast<size_t>(i)]
                     : net->stages[0].input_mems[i];
  }
  bm_device_mem_t out_mem(int i) const {
    return tagged_io ? output_mem[static_cast<size_t>(i)]
                     : net->stages[0].output_mems[i];
  }

  void release() {
    if (!handle) return;
    for (auto& m : input_mem) bm_free_device(handle, m);
    for (auto& m : output_mem) bm_free_device(handle, m);
    input_mem.clear();
    output_mem.clear();
  }
};

NetEngine::NetEngine() : impl_(new Impl()) {}

NetEngine::~NetEngine() {
  if (!impl_) return;
  // Stop first, then release, then drop the handle -- the same order the chat
  // engine uses, and for the same reason: a launch still in flight on another
  // thread (a request that was being served when the worker got its SIGTERM)
  // must finish before anything it wrote to is freed. Taking the mutex is what
  // waits for it; run() holds the same mutex for the whole launch-and-sync.
  {
    std::lock_guard<std::mutex> guard(impl_->mu);
    if (impl_->handle) {
      // Not fatal if this fails: the launch may already have been abandoned by
      // the driver, and the free below still has to happen. It is reported
      // because a sync that fails here is what a wedged TPU looks like.
      if (bm_thread_sync(impl_->handle) != BM_SUCCESS) {
        std::fprintf(stderr,
                     "[net] bm_thread_sync failed on teardown; freeing anyway\n");
      }
    }
  }

  impl_->release();
  if (impl_->bmrt) {
    // bmrt_destroy frees the graph's own device memory through libbmrt's
    // process-wide compute pool. That pool *resizes* when the net being
    // destroyed was the largest one left (ComputeMemory::Destroy ->
    // Resize, a free followed by a fresh malloc), and BMRT_ASSERT throws a
    // std::runtime_error when that malloc fails -- observed on the board as
    // "bm_alloc_gmem failed" then "BMRT_ASSERT" on every OCR unload.
    //
    // A throw escaping a destructor calls std::terminate, which killed the
    // worker instead of just failing the unload. Catching it here is not a
    // workaround for the resize itself (closing in reverse creation order is
    // what avoids that -- see OcrBackend.close); it is what keeps a destructor
    // from being able to abort the process at all. Nothing is left to report
    // to a caller at this point, so the log line is the whole response.
    try {
      bmrt_destroy(impl_->bmrt);
    } catch (const std::exception& e) {
      std::fprintf(stderr,
                   "[net] bmrt_destroy threw on teardown: %s -- the driver "
                   "reclaims the device memory when the handle closes\n",
                   e.what());
    } catch (...) {
      std::fprintf(stderr, "[net] bmrt_destroy threw an unknown exception on "
                           "teardown\n");
    }
    impl_->bmrt = nullptr;
  }
  if (impl_->handle) bm_dev_free(impl_->handle);
  delete impl_;
}

std::string NetEngine::last_error() const { return impl_->last_error; }
int NetEngine::num_inputs() const {
  return impl_->net ? impl_->net->input_num : 0;
}
int NetEngine::num_outputs() const {
  return impl_->net ? impl_->net->output_num : 0;
}
int NetEngine::num_stages() const { return impl_->num_stages; }

int NetEngine::input_dims(int index, int* dims, int cap) const {
  const Impl& e = *impl_;
  if (!e.net || index < 0 || index >= e.net->input_num) return -1;
  const bm_shape_t& s = e.net->stages[0].input_shapes[index];
  for (int i = 0; i < s.num_dims && i < cap; i++) dims[i] = s.dims[i];
  return s.num_dims;
}

int NetEngine::output_dims(int index, int* dims, int cap) const {
  const Impl& e = *impl_;
  if (!e.net || index < 0 || index >= e.net->output_num) return -1;
  const bm_shape_t& s = e.net->stages[0].output_shapes[index];
  for (int i = 0; i < s.num_dims && i < cap; i++) dims[i] = s.dims[i];
  return s.num_dims;
}

long long NetEngine::input_elements(int index) const {
  const Impl& e = *impl_;
  if (!e.net || index < 0 || index >= e.net->input_num) return -1;
  return Impl::elements(e.net->stages[0].input_shapes[index]);
}

long long NetEngine::output_elements(int index) const {
  const Impl& e = *impl_;
  if (!e.net || index < 0 || index >= e.net->output_num) return -1;
  return Impl::elements(e.net->stages[0].output_shapes[index]);
}

int NetEngine::input_dtype(int index) const {
  const Impl& e = *impl_;
  if (!e.net || index < 0 || index >= e.net->input_num) return -1;
  return static_cast<int>(e.net->input_dtypes[index]);
}

int NetEngine::output_dtype(int index) const {
  const Impl& e = *impl_;
  if (!e.net || index < 0 || index >= e.net->output_num) return -1;
  return static_cast<int>(e.net->output_dtypes[index]);
}

bool NetEngine::load(const std::string& model_path, int dev_id) {
  Impl& e = *impl_;
  if (bm_dev_request(&e.handle, dev_id) != BM_SUCCESS) {
    return e.fail("bm_dev_request failed");
  }
  e.bmrt = bmrt_create(e.handle);
  if (!e.bmrt) return e.fail("bmrt_create failed");
  bmrt_set_flags(e.bmrt, BM_RUNTIME_SHARE_MEM);
  if (!bmrt_load_bmodel(e.bmrt, model_path.c_str())) {
    return e.fail("bmrt_load_bmodel failed (wrong chip or corrupt file?): " + model_path);
  }

  const int count = bmrt_get_network_number(e.bmrt);
  if (count < 1) return e.fail("bmodel contains no graph");
  if (count > 1) {
    // Refused rather than "run the first one": a multi-graph file is a
    // pipeline whose order and wiring this class cannot know, and silently
    // picking one graph would answer a different question than the caller
    // asked. The OCR builds are one graph each; a future multi-graph build
    // needs its own engine, not a guess.
    return e.fail("bmodel contains " + std::to_string(count) +
                  " graphs; this engine runs exactly one");
  }
  const char** names = nullptr;
  bmrt_get_network_names(e.bmrt, &names);
  e.net = bmrt_get_network_info(e.bmrt, names[0]);
  free(names);
  if (!e.net) return e.fail("cannot read the graph's tensor info");

  if (e.net->input_num < 1 || e.net->output_num < 1) {
    return e.fail("graph has no input or no output");
  }
  e.num_stages = e.net->stage_num > 0 ? e.net->stage_num : 1;
  if (e.num_stages != 1) {
    // Refused for the reason in `in_mem`: one allocation per tensor is correct
    // only when there is one stage. Every shipped OCR build is single-stage, so
    // this refuses a build this engine was never tested against rather than
    // sizing its buffers wrongly.
    return e.fail("graph has " + std::to_string(e.num_stages) +
                  " stages; this engine runs single-stage graphs");
  }

  // Decide who owns the I/O memory, once, from the bmodel itself. The two modes
  // are not interchangeable: in tag mode the graph's own mems are synthetic and
  // every copy to them fails, so this is the difference between an engine that
  // runs and one that returns "copying input 0 to the device failed" for a
  // perfectly good bmodel (measured on .151).
  e.tagged_io = e.net->addr_mode == ADDR_MODE_IO_TAG ||
                e.net->addr_mode == ADDR_MODE_IO_TAG_FUSE;
  if (e.tagged_io) {
    // One buffer per tensor, sized in the graph's own dtype. `bmrt_tensor_ex`
    // would do this too, but it also wants an `bm_tensor_t` per call, and this
    // engine passes raw pointers -- so the allocation is explicit and the
    // tensor wrappers are built in `run` from these memories.
    e.input_mem.resize(static_cast<size_t>(e.net->input_num));
    e.output_mem.resize(static_cast<size_t>(e.net->output_num));
    for (int i = 0; i < e.net->input_num; i++) {
      const unsigned int bytes = static_cast<unsigned int>(
          Impl::elements(e.net->stages[0].input_shapes[i]) *
          e.dtype_bytes(e.net->input_dtypes[i]));
      if (bm_malloc_device_byte_heap_mask(e.handle, &e.input_mem[i], kNpuHeapMask,
                                          bytes) != BM_SUCCESS) {
        e.release();
        return e.fail("NPU heap exhausted allocating input " + std::to_string(i) +
                      " (" + std::to_string(bytes) + " bytes)");
      }
    }
    for (int i = 0; i < e.net->output_num; i++) {
      const unsigned int bytes = static_cast<unsigned int>(
          Impl::elements(e.net->stages[0].output_shapes[i]) *
          e.dtype_bytes(e.net->output_dtypes[i]));
      if (bm_malloc_device_byte_heap_mask(e.handle, &e.output_mem[i], kNpuHeapMask,
                                          bytes) != BM_SUCCESS) {
        e.release();
        return e.fail("NPU heap exhausted allocating output " + std::to_string(i) +
                      " (" + std::to_string(bytes) + " bytes)");
      }
    }
  }

  // One host buffer for the largest output. Sized in the graph's own dtype and
  // reused; the conversions to float happen per element on the way out.
  long long largest = 0;
  for (int i = 0; i < e.net->output_num; i++) {
    const long long bytes = Impl::elements(e.net->stages[0].output_shapes[i]) *
                            e.dtype_bytes(e.net->output_dtypes[i]);
    if (bytes > largest) largest = bytes;
  }
  e.host_out.assign(static_cast<size_t>(largest), 0);
  return true;
}

bool NetEngine::run(int stage, const float* const* in, float* const* out) {
  Impl& e = *impl_;
  std::lock_guard<std::mutex> guard(e.mu);
  if (!e.net) return e.fail("network engine is not loaded");
  if (stage < 0 || stage >= e.num_stages) {
    return e.fail("stage " + std::to_string(stage) + " out of range");
  }

  std::vector<bm_tensor_t> tin(static_cast<size_t>(e.net->input_num));
  std::vector<bm_tensor_t> tout(static_cast<size_t>(e.net->output_num));
  for (int i = 0; i < e.net->input_num; i++) {
    bmrt_tensor_with_device(&tin[static_cast<size_t>(i)], e.in_mem(i),
                            e.net->input_dtypes[i],
                            e.net->stages[stage].input_shapes[i]);
  }
  for (int i = 0; i < e.net->output_num; i++) {
    bmrt_tensor_with_device(&tout[static_cast<size_t>(i)], e.out_mem(i),
                            e.net->output_dtypes[i],
                            e.net->stages[stage].output_shapes[i]);
  }

  // Upload. A float32 input is the graph's own layout and goes straight across;
  // anything else is converted element by element into the graph's width, on
  // the host, because the driver copies bytes and would otherwise reinterpret
  // a float as two halves.
  for (int i = 0; i < e.net->input_num; i++) {
    if (!in || !in[i]) {
      return e.fail("run: null input pointer for input " + std::to_string(i));
    }
    const bm_device_mem_t mem = e.in_mem(i);
    const long long n = Impl::elements(e.net->stages[stage].input_shapes[i]);
    const bm_data_type_t dt = e.net->input_dtypes[i];
    if (dt == BM_FLOAT32) {
      if (bm_memcpy_s2d(e.handle, mem, const_cast<float*>(in[i])) != BM_SUCCESS) {
        return e.fail("copying input " + std::to_string(i) + " to the device failed");
      }
      continue;
    }
    const int width = e.dtype_bytes(dt);
    const size_t bytes = static_cast<size_t>(n) * static_cast<size_t>(width);
    if (e.host_in.size() < bytes) e.host_in.resize(bytes);
    for (long long k = 0; k < n; k++) {
      write_element(e.host_in.data(), k, in[i][k], dt);
    }
    if (bm_memcpy_s2d(e.handle, mem, e.host_in.data()) != BM_SUCCESS) {
      return e.fail("copying converted input " + std::to_string(i) + " failed");
    }
  }

  if (!bmrt_launch_tensor_ex(e.bmrt, e.net->name, tin.data(), e.net->input_num,
                             tout.data(), e.net->output_num, true, false)) {
    return e.fail(std::string("launch failed: ") + e.net->name);
  }
  if (bm_thread_sync(e.handle) != BM_SUCCESS) return e.fail("bm_thread_sync failed");

  for (int i = 0; i < e.net->output_num; i++) {
    if (!out || !out[i]) {
      return e.fail("run: null output pointer for output " + std::to_string(i));
    }
    const bm_device_mem_t mem = e.out_mem(i);
    const long long n = Impl::elements(e.net->stages[stage].output_shapes[i]);
    const bm_data_type_t dt = e.net->output_dtypes[i];
    if (dt == BM_FLOAT32) {
      if (bm_memcpy_d2s(e.handle, out[i], mem) != BM_SUCCESS) {
        return e.fail("copying output " + std::to_string(i) + " back failed");
      }
      continue;
    }
    const size_t bytes = static_cast<size_t>(n) * static_cast<size_t>(e.dtype_bytes(dt));
    if (e.host_out.size() < bytes) e.host_out.resize(bytes);
    if (bm_memcpy_d2s(e.handle, e.host_out.data(), mem) != BM_SUCCESS) {
      return e.fail("copying output " + std::to_string(i) + " back failed");
    }
    for (long long k = 0; k < n; k++) {
      out[i][k] = read_element(e.host_out.data(), k, dt);
    }
  }
  return true;
}

}  // namespace cv84x6
