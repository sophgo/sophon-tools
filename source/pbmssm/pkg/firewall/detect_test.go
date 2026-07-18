package firewall

import (
	"strings"
	"testing"
)

// fakeRunner 按命令名返回预设输出。
type fakeRunner struct {
	outs map[string]string // key = name + " " + strings.Join(args)
	errs map[string]error
	miss bool // 命令不存在时返 err
}

func (f fakeRunner) Run(name string, args ...string) (string, string, error) {
	k := name + " " + strings.Join(args, " ")
	if f.errs != nil {
		if e, ok := f.errs[k]; ok {
			return "", "not found", e
		}
	}
	if f.outs != nil {
		if o, ok := f.outs[k]; ok {
			return o, "", nil
		}
	}
	if f.miss {
		return "", "not found", errNotFound
	}
	return "", "", nil
}

var errNotFound = &notFoundErr{}

type notFoundErr struct{}

func (*notFoundErr) Error() string { return "not found" }

func TestCheckEnvironmentAllOK(t *testing.T) {
	// iptables/iptables-save/iptables-restore 都在，ufw 不在或 disabled
	r := fakeRunner{outs: map[string]string{
		"iptables -V":          "iptables v1.8",
		"iptables-save -V":     "v1.8",
		"iptables-restore -V":  "v1.8",
		"ufw status":           "Status: inactive",
		"test -w /etc/iptables/rules.v4": "",
	}}
	// which 检测：用 outs 模拟存在（返空串无错=存在）
	res := CheckEnvironment(r)
	if !res.OK {
		t.Fatalf("expected OK, issues=%+v", res.Issues)
	}
}

func TestCheckEnvironmentUfwActive(t *testing.T) {
	r := fakeRunner{outs: map[string]string{
		"iptables -V":                       "v",
		"iptables-save -V":                  "v",
		"iptables-restore -V":               "v",
		"ufw status":                        "Status: active",
		"test -w /etc/iptables/rules.v4":    "",
	}}
	res := CheckEnvironment(r)
	if res.OK {
		t.Fatal("expected NOT ok")
	}
	found := false
	for _, i := range res.Issues {
		if i.Check == "ufw" {
			found = true
			if i.FixCmd == "" {
				t.Error("FixCmd empty")
			}
		}
	}
	if !found {
		t.Error("ufw issue missing")
	}
}

func TestCheckEnvironmentMissingIptables(t *testing.T) {
	r := fakeRunner{miss: true}
	res := CheckEnvironment(r)
	if res.OK {
		t.Fatal("expected NOT ok")
	}
	hasIpt := false
	for _, i := range res.Issues {
		if i.Check == "iptables" {
			hasIpt = true
		}
	}
	if !hasIpt {
		t.Error("iptables issue missing")
	}
}

func TestDetectSSHPorts(t *testing.T) {
	// ss -tlnpH 输出含 sshd 监听 22 和 2222
	ssOut := "State  Recv-Q Send-Q Local Address:Port  Peer Address:Port  Process\n" +
		"LISTEN 0      128          0.0.0.0:22          0.0.0.0:*      users:((\"sshd\",pid=1,fd=3))\n" +
		"LISTEN 0      128          0.0.0.0:2222         0.0.0.0:*      users:((\"sshd\",pid=1,fd=4))\n" +
		"LISTEN 0      128          0.0.0.0:8080         0.0.0.0:*      users:((\"nginx\",pid=2,fd=5))\n"
	r := fakeRunner{outs: map[string]string{"ss -tlnpH": ssOut}}
	ports := DetectSSHPorts(r)
	if len(ports) != 2 || ports[0] != 22 || ports[1] != 2222 {
		t.Fatalf("got %v want [22 2222]", ports)
	}
}

func TestDetectSSHPortsEmpty(t *testing.T) {
	r := fakeRunner{miss: true}
	ports := DetectSSHPorts(r)
	if len(ports) != 0 {
		t.Fatalf("got %v want []", ports)
	}
}

func TestDetectSSHPortsNetstatFallback(t *testing.T) {
	// ss 不可用，netstat 输出含 sshd 在 22 和 2222，nginx 在 8080
	netstatOut := "tcp        0      0 0.0.0.0:22             0.0.0.0:*               LISTEN      1234/sshd\n" +
		"tcp        0      0 0.0.0.0:2222           0.0.0.0:*               LISTEN      1235/sshd\n" +
		"tcp6       0      0 :::8080                 :::*                    LISTEN      1236/nginx\n"
	r := fakeRunner{
		outs: map[string]string{"netstat -tlnp": netstatOut},
		errs: map[string]error{"ss -tlnpH": &notFoundErr{}},
	}
	ports := DetectSSHPorts(r)
	if len(ports) != 2 || ports[0] != 22 || ports[1] != 2222 {
		t.Fatalf("got %v want [22 2222]", ports)
	}
}

func TestDetectSophliteosPortsNetstatFallback(t *testing.T) {
	netstatOut := "tcp        0      0 0.0.0.0:443             0.0.0.0:*               LISTEN      777/sophliteos\n" +
		"tcp        0      0 0.0.0.0:8080            0.0.0.0:*               LISTEN      888/other\n"
	r := fakeRunner{
		outs: map[string]string{"netstat -tlnp": netstatOut},
		errs: map[string]error{"ss -tlnpH": &notFoundErr{}},
	}
	ports := DetectSophliteosPorts(r)
	if len(ports) != 1 || ports[0] != 443 {
		t.Fatalf("got %v want [443]", ports)
	}
}

func TestProtectPortsDedupSorted(t *testing.T) {
	// SSH=22, sophliteos=443, config 额外=[22,8080] → [22 443 8080] 去重排序
	// (config 额外端口通过 FirewallConfig 读，此处用 SSH+sophliteos 合并验证去重逻辑)
	a := []int{22, 443, 22, 8080}
	got := dedupSortPorts(a)
	if len(got) != 3 || got[0] != 22 || got[1] != 443 || got[2] != 8080 {
		t.Fatalf("got %v", got)
	}
}
