// docker_user_test.go
package firewall

import (
	"testing"
)

func TestDockerExtToContainerAllow(t *testing.T) {
	d := DockerRule{ID: 1, Scene: "ext_to_container", Params: mustParams(t, map[string]interface{}{"container_port": 8080, "proto": "tcp", "src": "10.0.0.0/8", "action": "allow"}), Enabled: true}
	if err := d.Validate(); err != nil {
		t.Fatal(err)
	}
	rules, err := d.Translate()
	if err != nil {
		t.Fatal(err)
	}
	// allow: 放行指定源 RETURN + 拒绝其他源 DROP（两条）
	if len(rules) != 2 {
		t.Fatalf("got %d want 2", len(rules))
	}
	if rules[0].Chain != "DOCKER-USER" {
		t.Errorf("chain=%s", rules[0].Chain)
	}
	// 第一条 RETURN（放行 10.0.0.0/8）
	hasReturn := false
	for _, r := range rules {
		for _, a := range r.Args {
			if a == "RETURN" {
				hasReturn = true
			}
		}
	}
	if !hasReturn {
		t.Error("missing RETURN for allow")
	}
}

func TestDockerContainerToExtDeny(t *testing.T) {
	d := DockerRule{ID: 2, Scene: "container_to_ext", Params: mustParams(t, map[string]interface{}{"container_cidr": "172.17.0.0/16", "dst_except": "10.0.0.0/8", "action": "deny"}), Enabled: true}
	rules, err := d.Translate()
	if err != nil {
		t.Fatal(err)
	}
	if len(rules) != 1 {
		t.Fatalf("got %d want 1", len(rules))
	}
	// 应含 -s 172.17.0.0/16 和 -d ! 10.0.0.0/8 和 DROP
	args := rules[0].Args
	hasSrc, hasDrop := false, false
	for i, a := range args {
		if a == "-s" && i+1 < len(args) && args[i+1] == "172.17.0.0/16" {
			hasSrc = true
		}
		if a == "DROP" {
			hasDrop = true
		}
	}
	if !hasSrc || !hasDrop {
		t.Errorf("missing src/drop: %v", args)
	}
}

func TestDockerValidateBadScene(t *testing.T) {
	d := DockerRule{Scene: "bogus", Params: "{}"}
	if err := d.Validate(); err == nil {
		t.Error("want error")
	}
}
