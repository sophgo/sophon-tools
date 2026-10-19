package main

// 网口枚举与默认网段推断：桌面版与 Web 版共用。

import (
	"net"
	"os"
	"sort"
	"strconv"
	"strings"
	"time"
)

// listScanInterfaces 列出可用的网口名（带 IPv4 地址的优先）。
func listScanInterfaces() []string {
	ifaces, err := net.Interfaces()
	if err != nil {
		return nil
	}
	var withIP, other []string
	for _, i := range ifaces {
		if i.Flags&net.FlagLoopback != 0 || i.Flags&net.FlagUp == 0 {
			continue
		}
		addrs, _ := i.Addrs()
		has4 := false
		for _, a := range addrs {
			if ipn, ok := a.(*net.IPNet); ok && ipn.IP.To4() != nil {
				has4 = true
				break
			}
		}
		if has4 {
			withIP = append(withIP, i.Name)
		} else {
			other = append(other, i.Name)
		}
	}
	return orderIfacesForScan(append(withIP, other...))
}

// guessLocalCIDR 猜一个默认网段（取该网口的第一个 IPv4 掩码网段）。
func guessLocalCIDR(iface string) string {
	if iface == "" {
		return ""
	}
	ifc, err := net.InterfaceByName(iface)
	if err != nil {
		return ""
	}
	addrs, _ := ifc.Addrs()
	for _, a := range addrs {
		if ipn, ok := a.(*net.IPNet); ok && ipn.IP.To4() != nil {
			// 归一到网络地址，便于用户直接点扫描
			ones, _ := ipn.Mask.Size()
			network := &net.IPNet{IP: ipn.IP.Mask(ipn.Mask), Mask: ipn.Mask}
			if ones >= 22 { // 太大会扫很久，仍按原样给出，用户可自行调整
				return network.String()
			}
			return network.String()
		}
	}
	return ""
}

func secondsDur(s int) time.Duration { return time.Duration(s) * time.Second }

// physicalIfaceOrder 把物理网口排在虚拟网口前面。
//
// 用户点开扫描对话框时，最可能想扫的是接设备的那块网卡，而不是
// docker0 / virbr0 / flannel / tun 这类虚拟接口。默认选中项按这个顺序取第一个。
func physicalIfaceOrder(names []string) []string {
	isVirtual := func(n string) bool {
		for _, p := range []string{"docker", "veth", "virbr", "br-", "flannel",
			"cni", "tun", "tap", "wg", "zt", "vnet", "lo"} {
			if len(n) >= len(p) && n[:len(p)] == p {
				return true
			}
		}
		return false
	}
	phys, virt := []string{}, []string{}
	for _, n := range names {
		if isVirtual(n) {
			virt = append(virt, n)
		} else {
			phys = append(phys, n)
		}
	}
	return append(phys, virt...)
}

// defaultRouteIfaces 返回有默认路由的网口名（按 metric 从小到大）。
//
// 用来决定扫描对话框的默认网口：用户想扫的通常是真正联网/接设备的那块，
// 而不是随便一块插着网线但没路由的网卡。
func defaultRouteIfaces() []string {
	b, err := os.ReadFile("/proc/net/route")
	if err != nil {
		return nil
	}
	type route struct {
		name   string
		metric int
	}
	var rs []route
	lines := strings.Split(string(b), "\n")
	for i, ln := range lines {
		if i == 0 || strings.TrimSpace(ln) == "" {
			continue
		}
		f := strings.Fields(ln)
		// 默认路由的判据是**目的地址**为 0.0.0.0（f[1]=00000000），
		// Gateway 此时是真实的下一跳地址，并不为 0——早先把它也当成判据，
		// 导致一条默认路由都没匹配到。
		if len(f) < 8 || f[1] != "00000000" {
			continue
		}
		m, _ := strconv.Atoi(f[6])
		rs = append(rs, route{f[0], m})
	}
	sort.Slice(rs, func(i, j int) bool { return rs[i].metric < rs[j].metric })
	out := make([]string, 0, len(rs))
	for _, r := range rs {
		out = append(out, r.name)
	}
	return out
}

// orderIfacesForScan 把「有默认路由的物理网口」排到最前。
func orderIfacesForScan(names []string) []string {
	pref := map[string]int{}
	for i, n := range defaultRouteIfaces() {
		pref[n] = i + 1
	}
	base := physicalIfaceOrder(names)
	sort.SliceStable(base, func(i, j int) bool {
		pi, iok := pref[base[i]]
		pj, jok := pref[base[j]]
		if iok != jok {
			return iok
		}
		if iok && jok {
			return pi < pj
		}
		return false
	})
	return base
}
