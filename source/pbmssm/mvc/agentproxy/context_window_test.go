package agentproxy

import (
	"strconv"
	"strings"
	"testing"
)

// 需求（Req2）：LLM ApiBase=sophnet → 上下文 200K；本地模型 → 20K。
func TestRewriteContextWindow(t *testing.T) {
	const sample = `default_model = "sophnet"

[[providers]]
name        = "sophnet"
kind        = "openai"
base_url    = "http://127.0.0.1:18080/v1"
model       = "DeepSeek-V4.1-Flash-1017"
api_key_env = "DEEPSEEK_API_KEY"
reasoning_protocol = "openai"
context_window = 200000
`
	cases := []struct {
		name   string
		api    string
		want   int
		toWhom string
	}{
		{"sophnet api → 200K", "https://www.sophnet.com/api/open-apis/v1", 200000, "sophnet"},
		{"local api → 20K", "http://127.0.0.1:8000/v1", 20000, "local"},
	}
	for _, c := range cases {
		out, changed, err := rewriteContextWindow([]byte(sample), contextWindowFor(c.api))
		if err != nil {
			t.Fatalf("%s: rewrite err = %v", c.name, err)
		}
		if !changed {
			t.Fatalf("%s: expected change", c.name)
		}
		if !strings.Contains(string(out), "context_window = "+strconv.Itoa(c.want)) {
			t.Errorf("%s: rewrote to %q, want context_window = %d (%s)", c.name, out, c.want, c.toWhom)
		}
		// provider 其余字段保持不变
		if !strings.Contains(string(out), `model       = "DeepSeek-V4.1-Flash-1017"`) {
			t.Errorf("%s: provider model field was clobbered", c.name)
		}
	}

	// 无 context_window 键 → 报错
	if _, _, err := rewriteContextWindow([]byte("default_model = \"sophnet\""), 200000); err == nil {
		t.Errorf("config without context_window should error")
	}
}
