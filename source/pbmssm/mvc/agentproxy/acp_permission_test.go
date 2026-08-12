package agentproxy

import (
	"bufio"
	"encoding/json"
	"strings"
	"testing"
	"time"
)

// TestDownlinkRequestPermNotifiesWithRequestID 验证 agent 发起的 request
// （session/request_permission）会触发 onNotify，且带上 JSON-RPC 请求 id 与原始 params。
func TestDownlinkRequestPermNotifiesWithRequestID(t *testing.T) {
	tr, pm := newStdIOTransport(t)
	defer tr.in.Close()
	defer tr.out.Close()

	var gotMethod string
	var gotParams json.RawMessage
	var gotReqID *int64
	client := NewClient(pm, nil, func(method string, params json.RawMessage, reqID *int64) {
		gotMethod = method
		gotParams = params
		gotReqID = reqID
	})
	defer client.Close()

	// 模拟 reasonix 发起一个 request_permission 请求（带 id）
	req := `{"jsonrpc":"2.0","id":42,"method":"session/request_permission","params":{"sessionId":"s1","toolCall":{"toolCallId":"gate-1","title":"Bash","kind":"bash","status":"pending"},"options":[{"optionId":"allow_once","name":"Allow","kind":"allow_once"}]}}`
	if err := tr.reply(json.RawMessage(req)); err != nil {
		t.Fatalf("inject request: %v", err)
	}

	waitFor(t, time.Second, "onNotify called", func() bool { return gotMethod != "" })
	if gotMethod != "session/request_permission" {
		t.Fatalf("onNotify method = %q, want session/request_permission", gotMethod)
	}
	if gotReqID == nil || *gotReqID != 42 {
		t.Fatalf("onNotify reqID = %v, want 42", gotReqID)
	}
	if !strings.Contains(string(gotParams), `"sessionId":"s1"`) {
		t.Fatalf("onNotify params missing sessionId: %s", gotParams)
	}
}

// TestResolvePermissionAllowRespondsRequest 验证 ResolvePermission(allow=true)
// 会以正确的 JSON-RPC 响应帧回给 request_permission 请求（id 对齐 + outcome=selected/allow_once）。
func TestResolvePermissionAllowRespondsRequest(t *testing.T) {
	tr, pm := newStdIOTransport(t)
	defer tr.in.Close()
	defer tr.out.Close()
	sc := bufio.NewScanner(tr.in)

	client := NewClient(pm, nil, nil)
	defer client.Close()

	const reqID = int64(7)
	if err := client.ResolvePermission(reqID, true); err != nil {
		t.Fatalf("ResolvePermission: %v", err)
	}

	resp := tr.readRawLine(t, sc)
	var frame struct {
		ID     int64  `json:"id"`
		Method string `json:"method,omitempty"`
		Result json.RawMessage `json:"result,omitempty"`
	}
	if err := json.Unmarshal(resp, &frame); err != nil {
		t.Fatalf("parse frame: %v (raw=%s)", err, resp)
	}
	if frame.ID != reqID {
		t.Fatalf("response id = %d, want %d", frame.ID, reqID)
	}
	// 响应是 result 帧（无 method），且 result 结构正确
	if frame.Method != "" {
		t.Fatalf("response should not have method, got %s", frame.Method)
	}
	var out struct {
		Outcome struct {
			Outcome  string `json:"outcome"`
			OptionID string `json:"optionId"`
		} `json:"outcome"`
	}
	if err := json.Unmarshal(frame.Result, &out); err != nil {
		t.Fatalf("parse result: %v (raw=%s)", err, frame.Result)
	}
	if out.Outcome.Outcome != "selected" || out.Outcome.OptionID != "allow_once" {
		t.Fatalf("allow outcome = %+v, want selected/allow_once", out.Outcome)
	}
}

// TestResolvePermissionDenyRespondsRequest 验证 ResolvePermission(allow=false)
// 会以 outcome=cancelled 回给 request_permission 请求。
func TestResolvePermissionDenyRespondsRequest(t *testing.T) {
	tr, pm := newStdIOTransport(t)
	defer tr.in.Close()
	defer tr.out.Close()
	sc := bufio.NewScanner(tr.in)

	client := NewClient(pm, nil, nil)
	defer client.Close()

	const reqID = int64(8)
	if err := client.ResolvePermission(reqID, false); err != nil {
		t.Fatalf("ResolvePermission: %v", err)
	}

	resp := tr.readRawLine(t, sc)
	var frame struct {
		Result json.RawMessage `json:"result,omitempty"`
	}
	if err := json.Unmarshal(resp, &frame); err != nil {
		t.Fatalf("parse frame: %v (raw=%s)", err, resp)
	}
	var out struct {
		Outcome struct {
			Outcome  string `json:"outcome"`
			OptionID string `json:"optionId,omitempty"`
		} `json:"outcome"`
	}
	if err := json.Unmarshal(frame.Result, &out); err != nil {
		t.Fatalf("parse result: %v (raw=%s)", err, frame.Result)
	}
	if out.Outcome.Outcome != "cancelled" {
		t.Fatalf("deny outcome = %+v, want cancelled", out.Outcome)
	}
}