package config

import "testing"

// 内置 key 的有效明文（仅测试用；生产代码以混淆字节保存，不落明文源码）。
const builtinPlaintext = "sk-cmljwbvgikztbawfjhhqxazetoasktbrjwifqbojjipiacrr"

func TestBuiltinKeyDecodes(t *testing.T) {
	if BuiltinKey() != builtinPlaintext {
		t.Errorf("BuiltinKey() decode mismatch")
	}
}

func TestEffectiveKey(t *testing.T) {
	d := DefaultConfig()
	p := d.Products[0].Embedder
	if !p.IsBuiltinKey() {
		t.Error("default embedder should use builtin key")
	}
	if p.EffectiveKey() != builtinPlaintext {
		t.Errorf("effective key mismatch")
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

func TestDefaultProductIsSE7(t *testing.T) {
	d := DefaultConfig()
	if len(d.Products) == 0 || d.Products[0].Name != "se7" {
		t.Fatalf("expected default se7 product, got %+v", d.Products)
	}
}
