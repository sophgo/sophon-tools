// Host checks of the real encoder's graph contract, pooling, fault handling
// and unload. The fixture supplies tensor storage, not a replacement engine.
#include "fake_bm.h"
#include "vl_embed_engine.h"
#include <cmath>
#include <cstdio>
#include <zlib.h>

extern "C" void* cv_vle_image_create(const unsigned char*, int, int, int*, int*, const char**);

namespace {
int checks = 0, failures = 0;
void check(bool ok, const char* message) {
  ++checks;
  if (!ok) { ++failures; std::fprintf(stderr, "FAIL: %s\n", message); }
}
constexpr int H = 2048, S = 64, P = 16;

void fixture(bool bucketed = false, int static_seq = 256, bool middle = false, bool wemm = false) {
  using namespace fake_bm;
  reset();
  for (auto* n : nets) delete n;
  nets.clear();
  const int seq = bucketed ? static_seq : S;
  std::map<int, FakeNet*> shared_blocks;
  auto add = [&](const std::string& name, std::vector<bm_shape_t> ins,
                std::vector<bm_data_type_t> types, std::vector<bm_shape_t> outs,
                bool dynamic) {
    auto* n = new FakeNet();
    n->name = name; n->in_shape = ins; n->in_dt = types; n->out_shape = outs;
    n->info.is_dynamic = dynamic;
    // Like BM_RUNTIME_SHARE_MEM, reuse each bucket's I/O across layers so
    // full-size boundary fixtures stay within the fake's 256 MiB heap.
    const bool share = seq > 256 && name.rfind("block_", 0) == 0;
    const int rows = ins[0].dims[1];
    if (share && shared_blocks.count(rows)) {
      n->in = shared_blocks[rows]->in;
      n->out = shared_blocks[rows]->out;
      n->out_dt = shared_blocks[rows]->out_dt;
      nets.push_back(n);
      return;
    }
    for (size_t i = 0; i < ins.size(); ++i) {
      auto bytes = elements_of(ins[i]) * (types[i] == BM_BFLOAT16 || types[i] == BM_FLOAT16 ? 2 : 4);
      n->in.push_back(mem(alloc_addr(bytes), bytes));
    }
    for (auto shape : outs) {
      auto bytes = elements_of(shape) * 2;
      n->out.push_back(mem(alloc_addr(bytes), bytes));
      n->out_dt.push_back(BM_BFLOAT16);
      std::memset(host_ptr(n->out.back().u.device.device_addr), 0, bytes);
    }
    nets.push_back(n);
    if (share) shared_blocks[rows] = n;
  };
  add(wemm ? "wemm_embedding" : "embedding", {shape2(1, seq)}, {BM_INT32}, {shape3(1, seq, H)}, false);
  add("vit", {shape2(P, 1536), shape2(P, 2), shape2(P, 4), shape3(P, 4, 1)},
      {BM_FLOAT32, BM_INT32, BM_INT32, BM_FLOAT32},
      std::vector<bm_shape_t>(wemm ? 1 : 4, shape2(P / 4, H)), true);
  if (!wemm) add("add", {shape2(1, seq * H), shape2(1, seq * H)},
      {BM_BFLOAT16, BM_BFLOAT16}, {shape2(1, seq * H)}, false);
  std::vector<int> buckets{S};
  if (bucketed) {
    buckets = {128};
    if (seq > 512) buckets.push_back(512);
    if (middle) buckets.push_back(1024);
    buckets.push_back(seq);
  }
  for (int bucket : buckets) {
    for (int i = 0; i < (wemm ? 24 : 28); ++i) {
      const bool linear = wemm && i % 4 != 3;
      std::vector<bm_shape_t> shapes{shape3(1, bucket, H), shape2(3, bucket)};
      std::vector<bm_data_type_t> types{BM_BFLOAT16, BM_INT32};
      if (linear) { shapes[1] = shape4(1, 16, 128, 128); types[1] = BM_FLOAT32; }
      if (bucketed && !linear) { shapes.push_back(shape4(1, 1, bucket, bucket)); types.push_back(BM_BFLOAT16); }
      add("block_" + std::to_string(i) + (bucketed ? "_s" + std::to_string(bucket) : ""),
          shapes, types, {shape3(1, bucket, H)}, !bucketed);
    }
  }
  for (auto* n : nets) {
    n->stage.input_mems = n->in.data(); n->stage.output_mems = n->out.data();
    n->stage.input_shapes = n->in_shape.data(); n->stage.output_shapes = n->out_shape.data();
    n->info.name = n->name.c_str(); n->info.stages = &n->stage; n->info.stage_num = 1;
    n->info.input_num = n->in.size(); n->info.output_num = n->out.size();
    n->info.input_dtypes = n->in_dt.data(); n->info.output_dtypes = n->out_dt.data();
  }
}

void seed_last_row(int count) {
  // Only the last non-padding row is nonzero. Truncation must precede L2
  // normalisation; the remaining 1984 dimensions deliberately have larger values.
  auto* raw = static_cast<uint16_t*>(fake_bm::host_ptr(
      fake_bm::nets.back()->out[0].u.device.device_addr));
  for (int j = 0; j < H; ++j) raw[(count - 1) * H + j] = j < 64 ? 0x3f80 : 0x4000;
}

void text_and_image() {
  fixture();
  cv84x6::VlEmbedEngine e;
  check(e.load("/dev/null", 0), "valid graph set loads");
  std::vector<int32_t> ids{1, 2, 3, 4};
  seed_last_row(ids.size());
  float out[64]; cv84x6::VlEmbedTimings timing;
  check(e.forward(ids.data(), ids.size(), nullptr, 0, 64, out, &timing), "text forward");
  for (float x : out) check(std::abs(x - 0.125f) < 1e-6, "last row / MRL / L2");
  check(fake_bm::launches_of("vit") == 0 && fake_bm::launches_of("add") == 0,
        "text does not run the visual tower or DeepStack");
  check(fake_bm::launches_of("block_27") == 1 && fake_bm::pending == 0,
        "all layers complete before returning");
  for (const auto& l : fake_bm::launches) if (l.net.rfind("block_", 0) == 0) {
    check(l.in_dims[0] == std::vector<int>({1, 4, H}), "dynamic hidden shape");
    check(l.in_dims[1] == std::vector<int>({3, 4}), "three compact position axes");
  }
  ids = {1, 151652, 151655, 151655, 151655, 151655, 151653, 2, 3};
  cv84x6::VisionInput image;
  image.grid_t = 1; image.grid_h = image.grid_w = 4;
  image.pixels.resize(P * 1536);
  seed_last_row(ids.size());
  check(e.forward(ids.data(), ids.size(), &image, 2, 64, out, &timing), "image forward");
  check(fake_bm::launches_of("vit") == 1 && fake_bm::launches_of("add") == 3,
        "one ViT and three DeepStack additions");
  auto count = fake_bm::launches.size();
  ids[2] = 1;
  check(!e.forward(ids.data(), ids.size(), &image, 2, 64, out, nullptr), "bad image span refused");
  check(fake_bm::launches.size() == count, "bad image refused before any launch");
  ids[0] = 151936;
  check(!e.forward(ids.data(), ids.size(), nullptr, 0, 64, out, nullptr), "bad vocabulary id refused");
  check(fake_bm::launches.size() == count, "bad id never reaches gather");
}

void failures_and_unload() {
  fixture();
  {
    cv84x6::VlEmbedEngine e;
    check(e.load("/dev/null", 0), "fault fixture loads");
    int32_t ids[]{1, 2}; float out[64];
    fake_bm::fail_sync = true;
    check(!e.forward(ids, 2, nullptr, 0, 64, out, nullptr), "sync error returned");
    auto count = fake_bm::launches.size();
    check(!e.forward(ids, 2, nullptr, 0, 64, out, nullptr), "fault stays latched");
    check(fake_bm::launches.size() == count, "faulted device is never reused");
  }
  fixture();
  fake_bm::nets.back()->in_dt[1] = BM_FLOAT32;
  {
    cv84x6::VlEmbedEngine e;
    check(!e.load("/dev/null", 0), "wrong position dtype refused at load");
  }
  fixture();
  {
    cv84x6::VlEmbedEngine e;
    check(e.load("/dev/null", 0), "unload fixture loads");
    fake_bm::bmrt_destroy_throws = true;
  }
  check(fake_bm::bmrt_destroys == 1, "bmrt_destroy called despite its throw");
}

void static_buckets() {
  fixture(true);
  cv84x6::VlEmbedEngine e;
  if (!e.load("/dev/null", 0)) { check(false, "static buckets load"); return; }
  for (int count : {4, 200}) {
    const int bucket = count <= 128 ? 128 : 256;
    const std::string suffix = "_s" + std::to_string(bucket);
    fake_bm::FakeNet *first = nullptr, *last = nullptr;
    for (auto* net : fake_bm::nets) {
      if (net->name == "block_0" + suffix) first = net;
      if (net->name == "block_27" + suffix) last = net;
    }
    auto* raw = static_cast<uint16_t*>(fake_bm::host_ptr(last->out[0].u.device.device_addr));
    for (int j = 0; j < H; ++j) raw[(count - 1) * H + j] = 0x3f80;
    std::vector<int32_t> ids(count, 2); float out[64];
    check(e.forward(ids.data(), count, nullptr, 0, 64, out, nullptr), "static forward");
    check(fake_bm::launches_of("block_27" + suffix) == 1, "smallest fitting bucket used");
    check(std::abs(out[0] - 0.125f) < 1e-6, "static last valid row, not padding");
    const auto* mask = static_cast<const uint16_t*>(fake_bm::host_ptr(first->in[2].u.device.device_addr));
    check(mask[0] == 0 && mask[1] == 0xc61c && mask[bucket] == 0 &&
          mask[bucket * bucket - 1] == 0, "causal mask including padded rows");
    const auto* pos = static_cast<const int32_t*>(fake_bm::host_ptr(first->in[1].u.device.device_addr));
    check(pos[bucket + count - 1] == count - 1 && pos[2 * bucket + count - 1] == count - 1 &&
          pos[count] == 0 && pos[bucket + count] == 0, "position axes use bucket stride and zero padding");
  }
}

void reject_incompatible_graphs() {
  fixture();
  fake_bm::nets.back()->out_shape[0].dims[2] = H / 2;
  {
    cv84x6::VlEmbedEngine engine;
    check(!engine.load("/dev/null", 0), "wrong final output stride refused");
  }
  fixture();
  fake_bm::nets[1]->out_shape[0].dims[1] = H / 2;
  {
    cv84x6::VlEmbedEngine engine;
    check(!engine.load("/dev/null", 0), "wrong visual output width refused");
  }
  fixture(true);
  fake_bm::nets.back()->info.stage_num = 0;
  {
    cv84x6::VlEmbedEngine engine;
    check(!engine.load("/dev/null", 0), "missing graph stage refused");
    int32_t ids[200]{}; float out[64];
    check(!engine.forward(ids, 200, nullptr, 0, 64, out, nullptr),
          "partial graph-set load cannot be used for forward");
  }
}

void optional_middle_bucket() {
  for (bool middle : {false, true}) {
    fixture(true, 2048, middle);
    cv84x6::VlEmbedEngine engine;
    if (!engine.load("/dev/null", 0)) { check(false, "old/new bucket model loads"); continue; }
    for (int count : {513, 1025}) {
      const int bucket = middle && count <= 1024 ? 1024 : 2048;
      const std::string name = "block_27_s" + std::to_string(bucket);
      fake_bm::FakeNet* last = nullptr;
      for (auto* net : fake_bm::nets) if (net->name == name) last = net;
      auto* raw = static_cast<uint16_t*>(fake_bm::host_ptr(last->out[0].u.device.device_addr));
      for (int j = 0; j < H; ++j) raw[(count-1)*H+j] = 0x3f80;
      const int before = fake_bm::launches_of(name);
      std::vector<int32_t> ids(count, 2); float out[64];
      check(engine.forward(ids.data(), count, nullptr, 0, 64, out, nullptr), "old/new model forwards long input");
      check(fake_bm::launches_of(name) == before+1, "optional 1024 bucket selected, legacy model falls back");
      check(std::abs(out[0]-0.125f) < 1e-6, "middle bucket pools real last token");
    }
  }
}

void oversized_image() {
  // A tiny compressed upload can declare huge decoded dimensions. Refuse
  // from the header, before allocating a full-size pixel/inflate buffer.
  auto be32 = [](uint32_t n) {
    std::string s;
    for (int shift : {24, 16, 8, 0}) s += static_cast<char>((n >> shift) & 255);
    return s;
  };
  std::string header = "IHDR" + be32(5000) + be32(5000);
  header.append("\x08\x02\0\0\0", 5);
  std::string png("\x89PNG\r\n\x1a\n", 8);
  png += be32(13) + header + be32(crc32(0, reinterpret_cast<const Bytef*>(header.data()), header.size()));
  int h = 0, w = 0;
  const char* error = nullptr;
  auto* image = cv_vle_image_create(reinterpret_cast<const unsigned char*>(png.data()),
                                   png.size(), 1024, &h, &w, &error);
  check(image == nullptr && error && std::string(error).find("source pixel limit") != std::string::npos,
        "oversized decoded image refused before allocation");
}

void wemm_independent_requests() {
  fixture(true, 256, false, true);
  cv84x6::VlEmbedEngine engine;
  if (!engine.load("/dev/null", 0)) {
    std::fprintf(stderr, "%s\n", engine.last_error().c_str());
    check(false, "WeMM graph loads"); return;
  }
  check(engine.is_wemm(), "WeMM family comes from the compiled graph");
  std::vector<int32_t> ids{1, 248053, 248056, 248056, 248056, 248056, 248054, 248077};
  cv84x6::VisionInput image;
  image.grid_t = 1; image.grid_h = image.grid_w = 4; image.pixels.resize(P * 1536);
  float output[64];
  for (int request = 0; request < 3; ++request) {
    std::vector<fake_bm::FakeNet*> recurrent;
    for (auto* net : fake_bm::nets) {
      if (net->name.rfind("block_", 0) == 0 && net->in_shape[0].dims[1] == 128) {
        if (net->in_shape[1].num_dims == 4 && net->in.size() == 2) {
          std::memset(fake_bm::host_ptr(net->in[1].u.device.device_addr), 0xa5, net->in[1].size);
          recurrent.push_back(net);
        }
        if (net->name == "block_23_s128") {
          auto* raw = static_cast<uint16_t*>(fake_bm::host_ptr(net->out[0].u.device.device_addr));
          for (int j = 0; j < H; ++j) raw[(ids.size() - 1) * H + j] = 0x3f80;
        }
      }
    }
    check(engine.forward(ids.data(), ids.size(), request == 1 ? &image : nullptr,
                         request == 1 ? 2 : 0, 64, output, nullptr), "WeMM text/image/text forwards");
    for (const auto& launch : fake_bm::launches) {
      if (launch.net.rfind("block_", 0) != 0 || launch.in_dims.size() != 2) continue;
      check(launch.in_dims[0] == std::vector<int>({1, 128, H}),
            "primitive GDN retains its compiled static bucket");
      check(launch.in_dims[1] == std::vector<int>({1, 16, 128, 128}),
            "GDN recurrent head count is never resized to the token count");
    }
    check(std::abs(output[0] - 0.125f) < 1e-6, "WeMM pools the last valid embedding token");
    check(recurrent.size() == 18, "18 linear attention layers");
    for (auto* net : recurrent) {
      const auto mem = net->in[1];
      const auto* bytes = static_cast<const unsigned char*>(fake_bm::host_ptr(mem.u.device.device_addr));
      check(std::all_of(bytes, bytes + mem.size, [](unsigned char x) { return x == 0; }),
            "whole recurrent state cleared for every independent request");
      check(fake_bm::memsets_of(mem.u.device.device_addr) == request + 1,
            "each recurrent state cleared once per request");
    }
  }
  check(fake_bm::launches_of("vit") == 1 && fake_bm::launches_of("add") == 0,
        "WeMM has one visual output and no DeepStack");
  check(fake_bm::launches_of("block_23_s128") == 3 && fake_bm::launches_of("block_24_s128") == 0,
        "WeMM executes exactly 24 layers");
}

void wemm_bucket_boundaries() {
  for (int n : {63, 64, 65, 128, 129, 255, 256}) {
    fixture(true, 256, false, true);
    cv84x6::VlEmbedEngine engine;
    check(engine.load("/dev/null", 0), "WeMM alignment fixture loads");
    const int bucket = n <= 128 ? 128 : 256;
    for (auto* net : fake_bm::nets) {
      if (net->name == "block_23_s" + std::to_string(bucket)) {
        auto* raw = static_cast<uint16_t*>(fake_bm::host_ptr(net->out[0].u.device.device_addr));
        for (int j = 0; j < H; ++j) raw[(n - 1) * H + j] = 0x3f80;
      }
    }
    std::vector<int32_t> ids(n, 1);
    float output[64];
    check(engine.forward(ids.data(), n, nullptr, 0, 64, output, nullptr),
          "GDN and full attention execute the same static bucket");
    for (const auto& launch : fake_bm::launches) {
      if (launch.net.rfind("block_", 0) != 0) continue;
      check(launch.in_dims[0] == std::vector<int>({1, bucket, H}),
            "all language layers retain the selected static bucket");
    }
    check(std::abs(output[0] - 0.125f) < 1e-6, "aligned path pools the valid final token");
  }
}

void wemm_rejects_incompatible_graphs() {
  for (int mutation = 0; mutation < 6; ++mutation) {
    fixture(true, 256, false, true);
    if (mutation == 0) {
      fake_bm::nets[2]->in_shape[1].dims[1] = 32; // wrong GDN head count
    } else if (mutation == 1) {
      fake_bm::nets[2]->in_dt[1] = BM_INT32; // a position tensor is not state
    } else if (mutation == 2) {
      fake_bm::nets.back()->info.is_dynamic = true;
    } else if (mutation == 3) {
      fake_bm::nets[2]->info.is_dynamic = true; // fused GDN is not supported
    } else if (mutation == 4) {
      fake_bm::nets[2]->in_dt[1] = BM_FLOAT16;
    } else {
      fake_bm::nets[2]->in_dt[1] = BM_BFLOAT16;
    }
    cv84x6::VlEmbedEngine engine;
    check(!engine.load("/dev/null", 0), "incompatible WeMM graph rejected at load");
    check(fake_bm::launches.empty(), "bad WeMM graph is never submitted to the device");
  }
}
}

int main() {
  text_and_image(); failures_and_unload(); oversized_image(); static_buckets(); reject_incompatible_graphs();
  optional_middle_bucket();
  wemm_independent_requests();
  wemm_bucket_boundaries();
  wemm_rejects_incompatible_graphs();
  std::printf("VL embedding native: %d/%d checks passed\n", checks - failures, checks);
  return failures ? 1 : 0;
}
