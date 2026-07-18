package firewall

import (
	"fmt"
	"regexp"
	"strconv"
	"strings"
)

type RawRule struct {
	Chain string   `json:"chain"`
	Args  []string `json:"args"`
}

var chainRe = regexp.MustCompile(`^[A-Z][A-Z0-9_-]*$`)

func (r RawRule) Validate() error {
	if !chainRe.MatchString(r.Chain) {
		return wrapInvalid(fmt.Errorf("invalid chain: %s", r.Chain))
	}
	for _, a := range r.Args {
		if !safeTokenRe.MatchString(a) {
			return wrapInvalid(fmt.Errorf("invalid arg: %s", a))
		}
	}
	return nil
}

type LiveRule struct {
	Chain  string `json:"chain"`
	Num    int    `json:"num"`
	Target string `json:"target"`
	Prot   string `json:"prot"`
	In     string `json:"in"`
	Out    string `json:"out"`
	Src    string `json:"src"`
	Dst    string `json:"dst"`
	Pkts   int64  `json:"pkts"`
	Bytes  int64  `json:"bytes"`
	Raw    string `json:"raw"`
}

func ListFilter(r CommandRunner) ([]LiveRule, error) {
	out, errStr, err := r.Run("iptables", "-t", "filter", "-nvL", "--line-numbers")
	if err != nil {
		return nil, fmt.Errorf("%s: %s", err, errStr)
	}
	return parseFilterList(out), nil
}

var chainHeaderRe = regexp.MustCompile(`^Chain (\S+) \(`)
var filterLineRe = regexp.MustCompile(`^\s*(\d+)\s+(\d+)\s+(\d+)\s+(\S+)\s+(\S+)\s+\S+\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s*(.*)$`)

func parseFilterList(out string) []LiveRule {
	var rules []LiveRule
	var currentChain string
	for _, line := range strings.Split(out, "\n") {
		if cm := chainHeaderRe.FindStringSubmatch(line); len(cm) == 2 {
			currentChain = cm[1]
			continue
		}
		m := filterLineRe.FindStringSubmatch(line)
		if len(m) != 11 {
			continue
		}
		num, _ := strconv.Atoi(m[1])
		pkts, _ := strconv.ParseInt(m[2], 10, 64)
		bytes, _ := strconv.ParseInt(m[3], 10, 64)
		rules = append(rules, LiveRule{
			Chain:  currentChain,
			Num:    num,
			Pkts:   pkts,
			Bytes:  bytes,
			Target: m[4],
			Prot:   m[5],
			In:     m[6],
			Out:    m[7],
			Src:    m[8],
			Dst:    m[9],
			Raw:    strings.TrimSpace(m[10]),
		})
	}
	return rules
}

func AddRaw(r CommandRunner, rule RawRule) error {
	if err := rule.Validate(); err != nil {
		return err
	}
	args := append([]string{"-A", rule.Chain}, rule.Args...)
	_, errStr, err := r.Run("iptables", args...)
	if err != nil {
		return fmt.Errorf("%s: %s", err, errStr)
	}
	return nil
}

func DeleteRaw(r CommandRunner, chain string, num int) error {
	if !chainRe.MatchString(chain) {
		return wrapInvalid(fmt.Errorf("invalid chain"))
	}
	_, errStr, err := r.Run("iptables", "-t", "filter", "-D", chain, strconv.Itoa(num))
	if err != nil {
		return fmt.Errorf("%s: %s", err, errStr)
	}
	return nil
}
