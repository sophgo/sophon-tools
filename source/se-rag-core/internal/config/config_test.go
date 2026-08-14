package config

import (
	"strings"
	"testing"
)

// 内置 key 是 gateway throwaway 网关钥匙，不落明文到测试文件（避免 git 里铺密钥指纹）。
// 这里只校验解码结果的形态与自洽性，不校验明文值本身。

// builtinKeyLen 为内置网关 key 的固定长度，用于捕获混淆字节被误改/截断。
const builtinKeyLen = 64

func TestBuiltinKeyDecodes(t *testing.T) {
	k := BuiltinKey()
	if k == "" {
		t.Fatal("BuiltinKey() returned empty")
	}
	if len(k) != builtinKeyLen {
		t.Errorf("BuiltinKey() length = %d, want %d", len(k), builtinKeyLen)
	}
	// 往返自洽：同一 key 再次混淆解码应得到相同结果
	re := make([]byte, len(builtinKeyEnc))
	for i, c := range builtinKeyEnc {
		re[i] = c ^ builtinKeyMask
	}
	if string(re) != k {
		t.Errorf("XOR roundtrip mismatch")
	}
}

func TestEffectiveKeyUsesBuiltinWhenEmpty(t *testing.T) {
	d := DefaultConfig()
	p := d.Products[0].Embedder
	if !p.IsBuiltinKey() {
		t.Error("default embedder should use builtin key")
	}
	if p.EffectiveKey() != BuiltinKey() {
		t.Errorf("effective key mismatch: want builtin, got %q", p.EffectiveKey())
	}
}

func TestEffectiveBaseURL(t *testing.T) {
	d := DefaultConfig()
	p := d.Products[0].Embedder
	// 内置 → 默认网关
	if p.EffectiveBaseURL() != GatewayBaseURL {
		t.Errorf("builtin effective base url = %q, want gateway %q", p.EffectiveBaseURL(), GatewayBaseURL)
	}
	// 自备 key → 回落官方 SiliconFlow，直达不被网关替换
	u := p
	u.APIKey = "user-key"
	if u.EffectiveBaseURL() != officialSiliconflowBaseURL {
		t.Errorf("user-key effective base url = %q, want official %q", u.EffectiveBaseURL(), officialSiliconflowBaseURL)
	}
}

func TestUserKeyOverrides(t *testing.T) {
	p := Provider{Type: "siliconflow", APIKey: "user-key", Model: "BAAI/bge-m3", Dim: 1024}
	if p.IsBuiltinKey() {
		t.Error("explicit api_key should disable builtin key")
	}
	if p.EffectiveKey() != "user-key" {
		t.Errorf("want user-key, got %q", p.EffectiveKey())
	}
}

func TestGatewayBaseURLShape(t *testing.T) {
	if !strings.Contains(GatewayBaseURL, "workers.dev") {
		t.Errorf("GatewayBaseURL %q should be the gateway worker host", GatewayBaseURL)
	}
}

func TestDefaultProductIsSE7(t *testing.T) {
	d := DefaultConfig()
	if len(d.Products) == 0 || d.Products[0].Name != "se7" {
		t.Fatalf("expected default se7 product, got %+v", d.Products)
	}
}