// The generic single-graph runner, driven against the fake bmrt.
//
// Three things a Python-side test cannot show, and which is why this runs as a
// C++ binary:
//
//   * a bmodel with more than one graph is refused rather than silently
//     running the first one -- a 94-graph chat build dropped into the OCR
//     directory is a configuration mistake, not a pipeline;
//   * the caller's float32 array reaches the graph intact, and the graph's
//     output comes back through the dtype conversion, in both directions -- the
//     fake echoes input to output so one call proves both;
//   * the tensor geometry reported by cv_net_info is what a caller sizes its
//     buffers from, so an off-by-one there is a heap overrun on the board.
//
// Build and run with tests/native/run_tests.sh (it compiles this file too).

#include "fake_bm.h"
#include "net_engine.h"

#include <cmath>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

namespace {

int g_checks = 0;
int g_failures = 0;

void check(bool ok, const std::string& what) {
  g_checks++;
  if (!ok) {
    g_failures++;
    std::fprintf(stderr, "FAIL: %s\n", what.c_str());
  }
}

// A model path the fake loader accepts (it only requires >= 1 graph).
const char* kPath = "/dev/null";

// -- 1: the geometry a caller reads ----------------------------------------
void test_info_reports_the_graphs_tensors() {
  // PP-OCRv6 det's real shape, and rec's: the two the service actually loads.
  fake_bm::build_single_graph("x", {1, 3, 736, 736}, {1, 1, 736, 736});
  cv84x6::NetEngine eng;
  check(eng.load(kPath, 0), "det-shaped graph loads");
  check(eng.num_inputs() == 1 && eng.num_outputs() == 1,
        "one input and one output");
  check(eng.num_stages() == 1, "one stage");

  int dims[8] = {0};
  check(eng.input_dims(0, dims, 8) == 4, "det input has rank 4");
  check(dims[0] == 1 && dims[1] == 3 && dims[2] == 736 && dims[3] == 736,
        "det input dims are 1x3x736x736");
  check(eng.input_elements(0) == 1LL * 3 * 736 * 736, "det input element count");

  std::memset(dims, 0, sizeof(dims));
  check(eng.output_dims(0, dims, 8) == 4, "det output has rank 4");
  check(dims[1] == 1 && dims[2] == 736 && dims[3] == 736,
        "det output is the probability map");
  check(eng.output_dtype(0) == BM_FLOAT32, "a float32 graph reports float32");

  // rec 1600: the widest tier, whose time axis is 200.
  fake_bm::build_single_graph("x", {1, 3, 48, 1600}, {1, 200, 18710});
  cv84x6::NetEngine rec;
  check(rec.load(kPath, 0), "rec-shaped graph loads");
  check(rec.output_elements(0) == 200LL * 18710, "rec output element count");
  check(rec.input_dtype(0) == BM_FLOAT32, "rec input reports float32");

  // Out-of-range indices are -1, not a read past the array.
  check(eng.input_dims(3, dims, 8) == -1, "an out-of-range input is refused");
  check(eng.input_elements(3) == -1, "an out-of-range input has no element count");
}

// -- 2: a multi-graph bmodel is refused ------------------------------------
void test_a_multi_graph_bmodel_is_refused() {
  // The chat layout: embedding + blocks + lm_head. Exactly the mistake of
  // pointing an OCR entry at a chat bmodel.
  fake_bm::build("qwen", true, 16, 64);
  check(fake_bm::nets.size() > 1, "the fake built several graphs");
  cv84x6::NetEngine eng;
  const bool ok = eng.load(kPath, 0);
  check(!ok, "a multi-graph bmodel does not load");
  check(eng.last_error().find("graphs") != std::string::npos,
        "the refusal names the graph count: " + eng.last_error());
}

// -- 3: float32 round trip -------------------------------------------------
void test_f32_input_reaches_the_graph_and_output_returns() {
  fake_bm::build_single_graph("x", {1, 2, 2, 2}, {1, 8});
  fake_bm::single_graph_echo = true;
  cv84x6::NetEngine eng;
  check(eng.load(kPath, 0), "graph loads");

  float in[8];
  for (int i = 0; i < 8; i++) in[i] = static_cast<float>(i) * 0.25f;
  float out[8] = {0};
  const float* ins[1] = {in};
  float* outs[1] = {out};
  check(eng.run(0, ins, outs), "run succeeds: " + eng.last_error());
  for (int i = 0; i < 8; i++) {
    check(std::fabs(out[i] - in[i]) < 1e-6f,
          "element " + std::to_string(i) + " came back unchanged");
  }
}

// -- 4: the graph's own width is converted, both directions -----------------
void test_f16_graph_is_converted_both_ways() {
  fake_bm::build_single_graph("x", {1, 3, 4, 4}, {1, 48}, /*fp16_io=*/true);
  fake_bm::single_graph_echo = true;
  cv84x6::NetEngine eng;
  check(eng.load(kPath, 0), "f16 graph loads");
  check(eng.input_dtype(0) == BM_FLOAT16, "an f16 graph reports f16");

  // Values exact in f16, so the assertion measures the conversion and not
  // rounding: 0.5, 1.0, 1.5, ... every one is a multiple of 1/2 with a small
  // exponent.
  std::vector<float> in(48);
  for (int i = 0; i < 48; i++) in[i] = static_cast<float>(i) * 0.5f;
  std::vector<float> out(48, 0.0f);
  const float* ins[1] = {in.data()};
  float* outs[1] = {out.data()};
  check(eng.run(0, ins, outs), "run succeeds: " + eng.last_error());
  for (int i = 0; i < 48; i++) {
    check(out[i] == in[i],
          "f16 element " + std::to_string(i) + " round-trips exactly (" +
              std::to_string(out[i]) + " vs " + std::to_string(in[i]) + ")");
  }

  // A value that is NOT exact in f16 must come back rounded, not truncated to
  // zero or reinterpreted -- the failure mode of copying 4 bytes into a 2-byte
  // tensor.
  std::vector<float> odd(48, 0.0f);
  odd[0] = 0.1f;  // f32 0.1 is not representable in f16
  const float* odd_in[1] = {odd.data()};
  float* odd_out[1] = {out.data()};
  check(eng.run(0, odd_in, odd_out), "run succeeds for the inexact case");
  check(std::fabs(out[0] - 0.1f) < 1e-3f,
        "0.1 survives as a half float (" + std::to_string(out[0]) + ")");
  check(out[0] > 0.0f, "and is not truncated to zero");
}

// -- 5: bad arguments are errors, not crashes ------------------------------
void test_bad_arguments_are_refused() {
  fake_bm::build_single_graph("x", {1, 1, 2, 2}, {1, 4});
  cv84x6::NetEngine eng;
  check(eng.load(kPath, 0), "graph loads");
  float in[4] = {1, 2, 3, 4};
  float out[4] = {0};
  const float* null_in[1] = {nullptr};
  const float* ins[1] = {in};
  float* null_out[1] = {nullptr};
  float* outs[1] = {out};

  check(!eng.run(0, null_in, outs), "a null input pointer is refused");
  check(!eng.last_error().empty(), "and says why");
  check(!eng.run(0, ins, null_out), "a null output pointer is refused");
  check(!eng.run(7, ins, outs), "an out-of-range stage is refused");

  // A launch failure surfaces as an error, not as stale output.
  fake_bm::fail_launch = true;
  check(!eng.run(0, ins, outs), "a failed launch is reported");
  check(eng.last_error().find("launch") != std::string::npos,
        "the failure names the launch: " + eng.last_error());
}

// -- 6: a tag-addressed graph owns no usable memory -----------------------
void test_tag_addressed_graph_gets_its_own_buffers() {
  // What tpu-mlir emits for a plain single graph, and what the first board run
  // of this engine hit: `addr_mode=2` (ADDR_MODE_IO_TAG) reports input_mems at
  // synthetic addresses like 0x40000000000, and every copy to them fails with
  // "out of range". The engine has to allocate its own tensors instead -- the
  // same thing bmrt_test does for every bmodel it runs.
  fake_bm::build_single_graph("x", {1, 3, 8, 8}, {1, 192},
                              /*fp16_io=*/false, /*addr_mode=*/ADDR_MODE_IO_TAG);
  check(fake_bm::nets[0]->info.addr_mode == ADDR_MODE_IO_TAG,
        "the fake presents a tag-addressed graph");
  fake_bm::single_graph_echo = true;

  cv84x6::NetEngine eng;
  const bool loaded = eng.load(kPath, 0);
  check(loaded, "a tag-addressed graph loads: " + eng.last_error());

  // The allocation the engine made must be real device memory: a launch that
  // used the graph's placeholder slots would be rejected by the fake's copy,
  // so reaching the echo at all proves the buffers were ours.
  std::vector<float> in(3 * 8 * 8);
  for (size_t i = 0; i < in.size(); i++) in[i] = static_cast<float>(i % 7);
  std::vector<float> out(192, 0.0f);
  const float* ins[1] = {in.data()};
  float* outs[1] = {out.data()};
  check(eng.run(0, ins, outs), "run succeeds on a tag-addressed graph: " +
                                   eng.last_error());
  for (int i = 0; i < 192; i++) {
    check(out[i] == in[static_cast<size_t>(i) % in.size()],
          "element " + std::to_string(i) + " echoed through the allocated buffer");
  }
}

// -- 7: a multi-stage graph is refused ------------------------------------
void test_a_multi_stage_graph_is_refused() {
  // One allocation per tensor is only correct for a single stage; a graph with
  // more would need one per stage, which this engine does not implement. Saying
  // so beats sizing its buffers wrongly.
  fake_bm::build_single_graph("x", {1, 1, 2, 2}, {1, 4});
  // The engine reads `stage_num` off the net info; the fixture's stage array has
  // one entry, which is enough because the refusal happens before any stage is
  // dereferenced.
  fake_bm::nets[0]->info.stage_num = 2;
  cv84x6::NetEngine eng;
  const bool loaded = eng.load(kPath, 0);
  check(!loaded, "a two-stage graph does not load");
  check(eng.last_error().find("stages") != std::string::npos,
        "the refusal names the stage count: " + eng.last_error());
}

// -- 8: a load with no graph at all ---------------------------------------
void test_an_empty_bmodel_is_refused() {
  fake_bm::reset();
  for (auto* n : fake_bm::nets) delete n;
  fake_bm::nets.clear();
  cv84x6::NetEngine eng;
  check(!eng.load(kPath, 0), "a bmodel with no graph does not load");
  // Which of the two refusals fires depends on whether the loader itself
  // rejects an empty file (it does, on a real board) or hands back zero
  // networks; both are the same answer to the caller and both must name the
  // file rather than crash.
  check(eng.last_error().find("/dev/null") != std::string::npos ||
            eng.last_error().find("no graph") != std::string::npos,
        "and says why: " + eng.last_error());
  check(eng.num_inputs() == 0 && eng.num_outputs() == 0,
        "a failed load leaves no half-initialised tensors behind");
}

// -- 9: teardown absorbs a throwing bmrt_destroy ---------------------------
void test_a_throwing_bmrt_destroy_does_not_escape_the_destructor() {
  // The board's failure, exactly: libbmrt's compute pool shrinks as nets are
  // destroyed, that shrink is a free + malloc, the malloc fails on the 84x6,
  // and BMRT_ASSERT throws a std::runtime_error. Coming out of a destructor it
  // called std::terminate and the OCR worker died on every unload.
  //
  // A destructor cannot report a failure to anyone, so the requirement is only
  // that it not abort the process: the next best thing is a log line and a
  // completed teardown (the driver reclaims the device memory when the handle
  // closes). This test fails loudly -- as a crash -- if the throw escapes,
  // which is the whole point.
  fake_bm::reset();
  fake_bm::build_single_graph("x", {1, 1, 4, 4}, {1, 4});
  int destroys_before = fake_bm::bmrt_destroys;
  {
    cv84x6::NetEngine eng;
    check(eng.load(kPath, 0), "the graph loads before the teardown test");
    fake_bm::bmrt_destroy_throws = true;
    // Leaving this scope runs ~NetEngine.
  }
  fake_bm::bmrt_destroy_throws = false;
  check(fake_bm::bmrt_destroys == destroys_before + 1,
        "bmrt_destroy was still called (the throw was absorbed, not skipped)");
}

// -- 10: teardown syncs before freeing ------------------------------------
void test_teardown_waits_for_an_in_flight_launch() {
  // A worker gets its SIGTERM while a request is still on the NPU. Freeing the
  // graph's memory before that launch retires is how a teardown leaves the TPU
  // busy for the next process, so the destructor has to sync first.
  fake_bm::reset();
  fake_bm::build_single_graph("x", {1, 1, 4, 4}, {1, 4});
  int syncs_before = fake_bm::syncs;
  {
    cv84x6::NetEngine eng;
    check(eng.load(kPath, 0), "the graph loads before the sync test");
    // load() itself may sync; the question is whether the destructor does.
    syncs_before = fake_bm::syncs;
  }
  check(fake_bm::syncs > syncs_before,
        "the destructor synced before freeing (a launch could still be in flight)");
}

}  // namespace

int main() {
  test_info_reports_the_graphs_tensors();
  test_a_multi_graph_bmodel_is_refused();
  test_f32_input_reaches_the_graph_and_output_returns();
  test_f16_graph_is_converted_both_ways();
  test_bad_arguments_are_refused();
  test_tag_addressed_graph_gets_its_own_buffers();
  test_a_multi_stage_graph_is_refused();
  test_an_empty_bmodel_is_refused();
  test_a_throwing_bmrt_destroy_does_not_escape_the_destructor();
  test_teardown_waits_for_an_in_flight_launch();
  std::printf("%d checks, %d failures\n", g_checks, g_failures);
  return g_failures == 0 ? 0 : 1;
}
