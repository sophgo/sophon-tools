// The fake libbmrt/libbmlib themselves. See fake_bm.h for what each knob means.
//
// Launches are queued: the graph's output is written by "execute()" only when a
// sync happens, exactly like the real non-blocking bmrt_launch_tensor_ex. That
// is what makes the deferred-sync optimisation testable -- if the engine read
// an output before syncing, it would read stale bytes and the value-based
// assertions below would fail.

#include "fake_bm.h"

#include <cstring>
#include <stdexcept>

namespace {

// What the fake graphs compute. Left trivial on purpose: the point is to give
// every stage a distinguishable value that a missing sync would corrupt.
inline int32_t fake_token(unsigned long long output_addr) {
  // Deterministic "argmax": derived from where the graph wrote, so a token id
  // is stable across runs of the same build.
  return static_cast<int32_t>((output_addr >> 8) % 30000);
}

inline void write_u32(unsigned long long addr, unsigned int size, int32_t v) {
  auto* p = static_cast<unsigned char*>(fake_bm::host_ptr(addr));
  if (!p || size < sizeof(v)) return;
  std::memcpy(p, &v, sizeof(v));
}

inline int32_t read_u32(const void* p) {
  int32_t v = 0;
  std::memcpy(&v, p, sizeof(v));
  return v;
}

// f16 <-> f32 for the single-graph echo. Deliberately the naive form: this fake
// is only ever fed values that are exact in f16 (see the test), so a rounding
// difference cannot masquerade as an engine bug.
inline float f16_to_f32_bits(uint16_t h) {
  const uint32_t sign = (h >> 15) & 1u;
  const uint32_t exp = (h >> 10) & 0x1fu;
  const uint32_t mant = h & 0x3ffu;
  uint32_t f;
  if (exp == 0) {
    f = sign << 31;
  } else if (exp == 31) {
    f = (sign << 31) | 0x7f800000u | (mant << 13);
  } else {
    f = (sign << 31) | ((exp + 127 - 15) << 23) | (mant << 13);
  }
  float out;
  std::memcpy(&out, &f, sizeof(out));
  return out;
}

inline uint16_t f32_to_f16_bits(float v) {
  uint32_t f;
  std::memcpy(&f, &v, sizeof(f));
  const uint32_t sign = (f >> 16) & 0x8000u;
  const uint32_t exp = (f >> 23) & 0xffu;
  const uint32_t mant = f & 0x7fffffu;
  if (exp == 0xffu) return static_cast<uint16_t>(sign | 0x7c00u);
  const int32_t e = static_cast<int32_t>(exp) - 127 + 15;
  if (e >= 0x1f) return static_cast<uint16_t>(sign | 0x7c00u);
  if (e <= 0) return static_cast<uint16_t>(sign);
  return static_cast<uint16_t>(sign | (static_cast<uint32_t>(e) << 10) | (mant >> 13));
}

}  // namespace

// ---- bmlib ----------------------------------------------------------------
extern "C" {

bm_status_t bm_dev_request(bm_handle_t* handle, int devid) {
  (void)devid;
  static int dummy = 0;
  *handle = reinterpret_cast<bm_handle_t>(&dummy);
  return BM_SUCCESS;
}

void bm_dev_free(bm_handle_t handle) { (void)handle; }

bm_status_t bm_malloc_device_byte_heap_mask(bm_handle_t handle, bm_device_mem_t* pmem,
                                            int heap_id_mask, unsigned int size) {
  (void)handle;
  (void)heap_id_mask;
  if (fake_bm::next_addr + size >= 0x10000000 + fake_bm::kHeapBytes) return BM_ERR_NOMEM;
  pmem->u.device.device_addr = fake_bm::alloc_addr(size);
  pmem->size = size;
  return BM_SUCCESS;
}

void bm_free_device(bm_handle_t handle, bm_device_mem_t mem) {
  (void)handle;
  (void)mem;
}

bm_device_mem_t bm_mem_from_device(unsigned long long device_addr, unsigned int len) {
  bm_device_mem_t m{};
  m.u.device.device_addr = device_addr;
  m.size = len;
  return m;
}

unsigned long long bm_mem_get_device_addr(struct bm_mem_desc mem) {
  return mem.u.device.device_addr;
}

unsigned int bm_mem_get_device_size(struct bm_mem_desc mem) { return mem.size; }

bm_status_t bm_memset_device_ext(bm_handle_t handle, void* value, int mode,
                                 bm_device_mem_t mem) {
  (void)handle;
  (void)mode;
  if (fake_bm::fail_memset) {
    fake_bm::fail_memset = false;
    return BM_ERR_FAILURE;
  }
  fake_bm::memsets.push_back(
      {mem.u.device.device_addr, static_cast<unsigned int>(mem.size)});
  auto* p = static_cast<unsigned char*>(fake_bm::host_ptr(mem.u.device.device_addr));
  if (!p) return BM_ERR_PARAM;
  std::vector<unsigned char> filled(mem.size, *static_cast<unsigned char*>(value));
  if (!fake_bm::device_write(mem.u.device.device_addr, filled.data(), filled.size()))
    return BM_ERR_PARAM;
  return BM_SUCCESS;
}

bm_status_t bm_memcpy_s2d_partial(bm_handle_t handle, bm_device_mem_t dst, void* src,
                                  unsigned int size) {
  (void)handle;
  auto* p = static_cast<unsigned char*>(fake_bm::host_ptr(dst.u.device.device_addr));
  if (!p || size > dst.size) return BM_ERR_PARAM;
  std::memcpy(p, src, size);
  return BM_SUCCESS;
}

// The whole-buffer copies. The engines mostly use the _partial forms (they copy
// n tokens into a SEQLEN buffer), but the generic network runner copies one
// tensor at a time, so these must exist and mean the same thing over the
// memory's full size.
bm_status_t bm_memcpy_s2d(bm_handle_t handle, bm_device_mem_t dst, void* src) {
  return bm_memcpy_s2d_partial(handle, dst, src, dst.size);
}

bm_status_t bm_memcpy_d2s(bm_handle_t handle, void* dst, bm_device_mem_t src) {
  (void)handle;
  if (!fake_bm::host_ptr(src.u.device.device_addr)) return BM_ERR_PARAM;
  // Returns whether the read had to fall back to pre-write bytes; the read
  // itself still produces the committed contents, as the hardware would.
  fake_bm::committed_read(src.u.device.device_addr,
                          static_cast<unsigned char*>(dst), src.size);
  return BM_SUCCESS;
}

bm_status_t bm_memcpy_d2s_partial(bm_handle_t handle, void* dst, bm_device_mem_t src,
                                  unsigned int size) {
  (void)handle;
  if (!fake_bm::host_ptr(src.u.device.device_addr) || size > src.size) return BM_ERR_PARAM;
  fake_bm::committed_read(src.u.device.device_addr,
                          static_cast<unsigned char*>(dst), size);
  return BM_SUCCESS;
}

bm_status_t bm_memcpy_d2d_byte(bm_handle_t handle, bm_device_mem_t dst,
                               size_t dst_offset, bm_device_mem_t src,
                               size_t src_offset, size_t size) {
  (void)handle;
  if (fake_bm::fail_d2d) {
    fake_bm::fail_d2d = false;
    return BM_ERR_FAILURE;
  }
  fake_bm::d2d_counts[{src.u.device.device_addr + src_offset,
                       dst.u.device.device_addr + dst_offset}]++;
  auto* d = static_cast<unsigned char*>(fake_bm::host_ptr(dst.u.device.device_addr));
  if (!d || !fake_bm::host_ptr(src.u.device.device_addr)) return BM_ERR_PARAM;
  // The copy kernel READS its source as a device consumer would: with writes
  // deferred (the field-SDK behaviour, see fake_bm.h), a source whose earlier
  // copy has not been synced still yields its pre-write bytes. That is the
  // whole defect -- a chained copy reads a buffer nobody has filled yet.
  std::vector<unsigned char> staged(size);
  fake_bm::committed_read(src.u.device.device_addr + src_offset, staged.data(), size);
  if (!fake_bm::device_write(dst.u.device.device_addr + dst_offset, staged.data(), size))
    return BM_ERR_PARAM;
  return BM_SUCCESS;
}

bm_status_t bm_thread_sync(bm_handle_t handle) {
  (void)handle;
  fake_bm::syncs++;
  fake_bm::pending = 0;
  // Everything launched or submitted so far retires at this boundary. This is
  // the only point at which a deferred device write becomes visible.
  fake_bm::commit_pending();
  fake_bm::sync_points.push_back(fake_bm::launches.size());
  if (fake_bm::fail_sync) {
    fake_bm::fail_sync = false;
    return BM_ERR_TIMEOUT;
  }
  return BM_SUCCESS;
}

// ---- bmrt -----------------------------------------------------------------
struct FakeRuntime {
  int unused;
};

void* bmrt_create(bm_handle_t bm_handle) {
  (void)bm_handle;
  static FakeRuntime rt;
  return &rt;
}

void bmrt_destroy(void* p_bmrt) {
  (void)p_bmrt;
  fake_bm::bmrt_destroys++;
  // The board's behaviour: libbmrt's compute pool resizes down as nets are
  // destroyed, that resize is a free + malloc, and on the 84x6 the malloc fails
  // and BMRT_ASSERT throws. Reproduced here on request so a host test can check
  // that the engine's destructor does not let it escape.
  if (fake_bm::bmrt_destroy_throws) {
    throw std::runtime_error("BMRuntime internal error.");
  }
}

void bmrt_set_flags(void* p_bmrt, uint32_t flags) {
  (void)p_bmrt;
  (void)flags;
}

bool bmrt_load_bmodel(void* p_bmrt, const char* bmodel_path) {
  (void)p_bmrt;
  (void)bmodel_path;
  return !fake_bm::nets.empty();
}

int bmrt_get_network_number(void* p_bmrt) {
  (void)p_bmrt;
  return static_cast<int>(fake_bm::nets.size());
}

void bmrt_get_network_names(void* p_bmrt, const char*** network_names) {
  (void)p_bmrt;
  // The engine frees this array, so hand out a malloc'd, NULL-terminated copy.
  auto** names = static_cast<const char**>(
      std::malloc(sizeof(const char*) * (fake_bm::nets.size() + 1)));
  for (size_t i = 0; i < fake_bm::nets.size(); i++)
    names[i] = fake_bm::nets[i]->name.c_str();
  names[fake_bm::nets.size()] = nullptr;
  *network_names = names;
}

const bm_net_info_t* bmrt_get_network_info(void* p_bmrt, const char* net_name) {
  (void)p_bmrt;
  for (auto* n : fake_bm::nets)
    if (n->name == net_name) return &n->info;
  return nullptr;
}

size_t bmrt_data_type_size(bm_data_type_t dtype) {
  switch (dtype) {
    case BM_FLOAT32:
      return 4;
    case BM_FLOAT16:
    case BM_BFLOAT16:
      return 2;
    case BM_INT32:
      return 4;
    default:
      return 1;
  }
}

void bmrt_tensor_with_device(bm_tensor_t* tensor, bm_device_mem_t device_mem,
                             bm_data_type_t dtype, bm_shape_t shape) {
  tensor->device_mem = device_mem;
  tensor->dtype = dtype;
  tensor->shape = shape;
  tensor->st_mode = BM_STORE_1N;
}

bool bmrt_launch_tensor_ex(void* p_bmrt, const char* net_name,
                           const bm_tensor_t input_tensors[], int input_num,
                           bm_tensor_t output_tensors[], int output_num,
                           bool user_mem, bool user_stmode) {
  (void)p_bmrt;
  (void)output_num;
  (void)user_mem;
  (void)user_stmode;
  if (fake_bm::fail_launch) {
    fake_bm::fail_launch = false;
    return false;
  }
  if (fake_bm::pending > 0) fake_bm::overlap_launches++;
  fake_bm::pending++;

  fake_bm::Launch l;
  l.net = net_name;
  // Capture inputs before outputs are written: the fake allocator may reuse an
  // input address for a later output allocation.
  for (int i = 0; i < input_num; i++) {
    auto* p = static_cast<unsigned char*>(
        fake_bm::host_ptr(input_tensors[i].device_mem.u.device.device_addr));
    // A word-wide int input is a token id (embedding / embedding_cache) or a
    // position triple; record its first element either way.
    l.int_inputs.push_back(input_tensors[i].dtype == BM_INT32 && p
                               ? read_u32(p)
                               : 0);
    std::vector<int> dims;
    for (int d = 0; d < input_tensors[i].shape.num_dims; d++)
      dims.push_back(input_tensors[i].shape.dims[d]);
    l.in_dims.push_back(std::move(dims));
  }
  if (input_num > 0 && input_tensors[0].dtype == BM_INT32) l.first_input = l.int_inputs[0];
  // A token id the embedding table cannot hold. Record it rather than fail: the
  // engine must reject such a prompt before launching anything, and a fixture
  // that fails the launch instead would let a missing check look like a
  // handled error (and would set the engine's fatal `fault`).
  if (fake_bm::vocab > 0 && input_tensors[0].dtype == BM_INT32 &&
      input_tensors[0].device_mem.size == 4) {
    const int32_t id = l.first_input;
    if (id < 0 || id >= fake_bm::vocab) fake_bm::out_of_range_id_launches++;
  }
  // A value keyed on the output address alone would be a constant, and a stale
  // read of a chained copy would then be indistinguishable from a fresh one.
  // `chain_hidden` makes output[0] a verbatim copy of the graph's input[0]
  // instead, so a value planted at the head of the chain only reaches the
  // pooled row when every copy that carried it was ordered.
  if (fake_bm::chain_hidden && input_num > 0 && output_num > 0 &&
      input_tensors[0].dtype == output_tensors[0].dtype) {
    const unsigned int in_size = input_tensors[0].device_mem.size;
    const unsigned int out_size = output_tensors[0].device_mem.size;
    const unsigned int size = std::min(in_size, out_size);
    std::vector<unsigned char> staged(size);
    if (fake_bm::committed_read(input_tensors[0].device_mem.u.device.device_addr,
                                staged.data(), size))
      fake_bm::stale_input_launches++;
    if (!fake_bm::device_write(output_tensors[0].device_mem.u.device.device_addr,
                               staged.data(), size))
      return false;
    fake_bm::launches.push_back(l);
    return true;
  }
  for (int i = 0; i < output_num; i++) {
    l.out_addrs.push_back(output_tensors[i].device_mem.u.device.device_addr);
    if (fake_bm::single_graph_echo && input_num > 0) {
      // Echo the input into the output, element for element, in each tensor's
      // own width. A test can then tell "the engine uploaded my array" and
      // "the engine converted the result back" from a single call.
      auto* src = static_cast<const unsigned char*>(
          fake_bm::host_ptr(input_tensors[0].device_mem.u.device.device_addr));
      auto* dst = static_cast<unsigned char*>(
          fake_bm::host_ptr(output_tensors[i].device_mem.u.device.device_addr));
      if (src && dst) {
        const long long in_n = fake_bm::elements_of(input_tensors[0].shape);
        const long long out_n = fake_bm::elements_of(output_tensors[i].shape);
        if (in_n > 0 && out_n > 0) {
          for (long long k = 0; k < out_n; k++) {
            float v = input_tensors[0].dtype == BM_FLOAT16
                          ? f16_to_f32_bits(
                                reinterpret_cast<const uint16_t*>(src)[k % in_n])
                          : reinterpret_cast<const float*>(src)[k % in_n];
            if (output_tensors[i].dtype == BM_FLOAT16) {
              reinterpret_cast<uint16_t*>(dst)[k] = f32_to_f16_bits(v);
            } else {
              reinterpret_cast<float*>(dst)[k] = v;
            }
          }
        }
      }
      fake_bm::launches.push_back(l);
      continue;
    }
    // Pretend the graph ran: write a value that depends on the launch order, so
    // an output read before the sync yields a different number. The write is a
    // device write, so it obeys the same retirement rule as a copy kernel. Only
    // the first word is written -- fixtures seed the pooled row further in, and
    // a whole-buffer clear here would erase that seed rather than model a graph.
    if (output_tensors[i].device_mem.size >= sizeof(int32_t)) {
      const int32_t v = fake_token(output_tensors[i].device_mem.u.device.device_addr) +
                        static_cast<int32_t>(fake_bm::launches.size());
      std::vector<unsigned char> staged(sizeof(v));
      std::memcpy(staged.data(), &v, sizeof(v));
      if (!fake_bm::device_write(output_tensors[i].device_mem.u.device.device_addr,
                                 staged.data(), staged.size()))
        return false;
    }
  }
  fake_bm::launches.push_back(l);
  return true;
}

}  // extern "C"
