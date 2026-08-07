package firewall

import (
	"errors"
	"strings"
	"testing"
)

// B1 回归：无 Docker 设备（DOCKER-USER 链不存在）CleanManaged 必须跳过该链而不是报错。
func TestCleanManagedNonDocker(t *testing.T) {
	r := &fakeRunner{}
	r.respond = func(name string, args []string) (string, string, error) {
		j := name + " " + strings.Join(args, " ")
		switch {
		case strings.Contains(j, "-L DOCKER-USER"):
			return "", "iptables: No chain/target/match by that name.", errors.New("exit status 1")
		case strings.Contains(j, "-L INPUT"):
			return "1  bmssm-fw-intent 1  tcp dpt:8080\n2  bmssm-fw-protect deadbeef tcp dpt:22\n", "", nil
		}
		return "", "", nil
	}
	if err := CleanManaged(r); err != nil {
		t.Fatalf("CleanManaged on non-Docker device must not fail: %v", err)
	}
	// INPUT 的受管规则（intent + protect 遗留）被删
	if r.count("-D INPUT") == 0 {
		t.Error("expected INPUT managed rule deletion")
	}
	// DOCKER-USER 只尝试列表，不应尝试 -D（链不存在）
	if r.count("-D DOCKER-USER") != 0 {
		t.Error("must not delete from absent DOCKER-USER chain")
	}
}

// Docker 设备：DOCKER-USER 链存在且带旧版 docker 受管规则 → 正常清理。
func TestCleanManagedDockerLegacy(t *testing.T) {
	r := &fakeRunner{}
	r.respond = func(name string, args []string) (string, string, error) {
		j := name + " " + strings.Join(args, " ")
		switch {
		case strings.Contains(j, "-L DOCKER-USER"):
			return "1  bmssm-fw-docker 1  -p tcp --dport 8080 -j DROP\n", "", nil
		case strings.Contains(j, "-L INPUT"):
			return "", "", nil
		}
		return "", "", nil
	}
	if err := CleanManaged(r); err != nil {
		t.Fatalf("CleanManaged: %v", err)
	}
	if r.count("-D DOCKER-USER") == 0 {
		t.Error("expected DOCKER-USER managed rule deletion")
	}
}

// S9 语义保留：INPUT 列表失败必须报错（不能静默判定"已清干净"）。
func TestCleanManagedInputListError(t *testing.T) {
	r := &fakeRunner{}
	r.respond = func(name string, args []string) (string, string, error) {
		j := name + " " + strings.Join(args, " ")
		if strings.Contains(j, "-L INPUT") {
			return "", "iptables: Permission denied (you must be root)", errors.New("exit status 3")
		}
		return "", "", nil
	}
	if err := CleanManaged(r); err == nil {
		t.Fatal("INPUT list failure must abort CleanManaged (S9 strict)")
	}
}

// DOCKER-USER 列表成功但删除失败：best-effort 记警告继续，不中止。
func TestCleanManagedDockerDeleteErrorTolerated(t *testing.T) {
	r := &fakeRunner{}
	r.respond = func(name string, args []string) (string, string, error) {
		j := name + " " + strings.Join(args, " ")
		switch {
		case strings.Contains(j, "-L DOCKER-USER"):
			return "1  bmssm-fw-docker 1  -j DROP\n", "", nil
		case strings.Contains(j, "-D DOCKER-USER"):
			return "", "iptables: Bad rule (does a matching rule exist in that chain?)", errors.New("exit status 1")
		}
		return "", "", nil
	}
	if err := CleanManaged(r); err != nil {
		t.Fatalf("DOCKER-USER -D failure must not abort CleanManaged: %v", err)
	}
}
