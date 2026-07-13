use lexopt;
use serde_yaml;
use serde_yaml::{Mapping, Value};
use std::env;
use std::fs;
use std::io::Write;
use std::process::exit;
use std::process::Command;

// ============ 数据结构 ============

/// 一个地址族(v4 或 v6),可含多个地址
struct Family {
    /// (地址, 前缀)
    addrs: Vec<(String, u8)>,
    gateway: Option<String>,
    dns: Option<String>,
    is_dhcp: bool,
}

/// 一条 IPv4 静态路由
struct Route {
    to: String,
    to_prefix: u8,
    via: Option<String>,
    table: Option<String>,
}

/// 路由策略(from/to 可选,自带 table)
struct Policy {
    from: Option<(String, u8)>,
    to: Option<(String, u8)>,
    table: Option<String>,
}

/// 完整配置(旧模式产单实例,4 元组模式产多实例)
struct Config {
    net_device: String,
    family1_is_v6: bool,
    v4: Option<Family>,
    v6: Option<Family>,
    routes: Vec<Route>,
    policies: Vec<Policy>,
    dry_run: bool,
}

impl Config {
    fn parse() -> Result<Self, lexopt::Error> {
        use lexopt::prelude::*;

        let mut positional: Vec<String> = Vec::new();
        let mut dry_run = false;
        let mut parser = lexopt::Parser::from_env();
        while let Some(arg) = parser.next()? {
            match arg.clone() {
                Value(val) => positional.push(val.into_string()?),
                Long(name) if name == "dry-run" => dry_run = true,
                Short('n') => dry_run = true,
                _ => return Err(arg.unexpected()),
            }
        }

        if positional.is_empty() {
            return Err("missing required argument: net_device".into());
        }
        let net_device = positional[0].clone();
        let rest: Vec<String> = positional[1..].to_vec();

        // 双模式:先旧模式,有剩余 token 则切 4 元组
        let mut cfg = match try_old_mode(&net_device, &rest)? {
            Some(c) => c,
            None => parse_4tuple(&net_device, &rest)?,
        };
        cfg.dry_run = dry_run;
        Ok(cfg)
    }
}

// ============ 旧模式(IP-only,尾部可省,向后兼容)============

/// 旧模式仅处理 IP-only:family1(尾部可省)+ 可选 family2。无路由/策略/额外地址。
/// 干净消费完所有 token → Some;有剩余 → None(切 4 元组)。
fn try_old_mode(net_device: &str, rest: &[String]) -> Result<Option<Config>, lexopt::Error> {
    if net_device.is_empty() {
        return Err("net_device must not be empty".into());
    }
    if rest.is_empty() {
        return Err("missing required argument: ip".into());
    }
    let addr1 = &rest[0];
    if addr1.is_empty() {
        return Err("missing required argument: ip".into());
    }
    let addr1 = addr1.clone();
    let family1_is_v6 = looks_like_ipv6(&addr1);
    let family1_is_v4 = !family1_is_v6;
    let mut i = 1usize;

    let (nm, gw, dns, jumped) = fill_family1_optional(rest, &mut i, family1_is_v4);
    let mut ipv6 = None;
    let mut ipv6_prefix = None;
    let mut ipv6_gateway = None;
    let mut ipv6_dns = None;

    if jumped {
        // family1 可选槽中遇到 v6/dhcp → 进 family2
        fill_family2(
            rest, &mut i, &mut ipv6, &mut ipv6_prefix, &mut ipv6_gateway, &mut ipv6_dns,
        );
    } else if family1_is_v4 {
        // family1 之后若紧跟 v6/dhcp → family2
        if let Some(t) = rest.get(i) {
            if !t.is_empty() && jumps_to_family2(t) {
                fill_family2(
                    rest, &mut i, &mut ipv6, &mut ipv6_prefix, &mut ipv6_gateway, &mut ipv6_dns,
                );
            }
        }
    }

    // 有剩余(路由/策略/额外地址)→ 切 4 元组
    if i < rest.len() {
        return Ok(None);
    }

    // 构造 IP-only Config
    let (v4, v6) = if family1_is_v6 {
        validate_ip(&addr1, true)?;
        validate_opt_gateway(&gw, true)?;
        validate_opt_dns(&dns)?;
        let prefix = match &nm {
            Some(m) => parse_prefix(m, 128)?,
            None => 128,
        };
        let v6f = Family {
            addrs: vec![(addr1, prefix)],
            gateway: gw,
            dns,
            is_dhcp: false,
        };
        (None, Some(v6f))
    } else {
        let is_dhcp4 = is_dhcp_token(&addr1);
        let v4f = if is_dhcp4 {
            validate_opt_gateway(&gw, false)?;
            validate_opt_dns(&dns)?;
            Family { addrs: vec![], gateway: gw, dns, is_dhcp: true }
        } else {
            validate_ip(&addr1, false)?;
            validate_opt_gateway(&gw, false)?;
            validate_opt_dns(&dns)?;
            let prefix = match &nm {
                Some(m) => mask_to_prefix_checked(m, 32)?,
                None => 32,
            };
            Family { addrs: vec![(addr1, prefix)], gateway: gw, dns, is_dhcp: false }
        };
        let v6f = if ipv6.is_some() {
            let is_dhcp6 = ipv6.as_deref().map(is_dhcp_token).unwrap_or(false);
            if is_dhcp6 {
                validate_opt_gateway(&ipv6_gateway, true)?;
                validate_opt_dns(&ipv6_dns)?;
                Some(Family { addrs: vec![], gateway: ipv6_gateway, dns: ipv6_dns, is_dhcp: true })
            } else {
                let a = ipv6.as_deref().unwrap();
                validate_ip(a, true)?;
                validate_opt_gateway(&ipv6_gateway, true)?;
                validate_opt_dns(&ipv6_dns)?;
                let prefix = match &ipv6_prefix {
                    Some(m) => parse_prefix(m, 128)?,
                    None => 128,
                };
                Some(Family {
                    addrs: vec![(a.to_string(), prefix)],
                    gateway: ipv6_gateway,
                    dns: ipv6_dns,
                    is_dhcp: false,
                })
            }
        } else {
            None
        };
        (Some(v4f), v6f)
    };

    Ok(Some(Config {
        net_device: net_device.to_string(),
        family1_is_v6,
        v4,
        v6,
        routes: Vec::new(),
        policies: Vec::new(),
        dry_run: false,
    }))
}

// ============ 4 元组模式(IP+其它)============

fn parse_4tuple(net_device: &str, rest: &[String]) -> Result<Config, lexopt::Error> {
    if net_device.is_empty() {
        return Err("net_device must not be empty".into());
    }
    if rest.is_empty() {
        return Err("missing required argument: ip".into());
    }
    let mut i = 0usize;
    let addr1 = rest
        .get(i)
        .filter(|s| !s.is_empty())
        .ok_or("missing required argument: ip")?
        .clone();
    i += 1;
    let family1_is_v6 = looks_like_ipv6(&addr1);
    let family1_is_dhcp = is_dhcp_token(&addr1);

    let mut v4: Option<Family> = None;
    let mut v6: Option<Family> = None;

    if family1_is_v6 {
        // v6 family1:4 元组(addr1 已消费,读 prefix/gw/dns)
        validate_ip(&addr1, true)?;
        let (prefix, gw, dns) = read_3slots(rest, &mut i);
        validate_opt_gateway(&gw, true)?;
        validate_opt_dns(&dns)?;
        let p = match &prefix {
            Some(m) => parse_prefix(m, 128)?,
            None => 128,
        };
        v6 = Some(Family { addrs: vec![(addr1, p)], gateway: gw, dns, is_dhcp: false });
    } else if family1_is_dhcp {
        // dhcp 单 token
        v4 = Some(Family { addrs: vec![], gateway: None, dns: None, is_dhcp: true });
    } else {
        // v4 static family1:4 元组(addr1 已消费,读 mask/gw/dns)
        validate_ip(&addr1, false)?;
        let (mask, gw, dns) = read_3slots(rest, &mut i);
        validate_opt_gateway(&gw, false)?;
        validate_opt_dns(&dns)?;
        let p = match &mask {
            Some(m) => mask_to_prefix_checked(m, 32)?,
            None => 32,
        };
        v4 = Some(Family { addrs: vec![(addr1, p)], gateway: gw, dns, is_dhcp: false });
    }

    let mut routes: Vec<Route> = Vec::new();
    let mut policies: Vec<Policy> = Vec::new();

    loop {
        let pos1 = match rest.get(i) {
            Some(s) if !s.is_empty() => s.clone(),
            _ => break,
        };
        // family2 门:family1 为 v4 且 pos1 为 v6/dhcp
        if !family1_is_v6 && jumps_to_family2(&pos1) {
            i += 1; // 消费 pos1(family2 addr/dhcp)
            if is_dhcp_token(&pos1) {
                v6 = Some(Family { addrs: vec![], gateway: None, dns: None, is_dhcp: true });
            } else {
                validate_ip(&pos1, true)?;
                let (prefix, gw, dns) = read_3slots(rest, &mut i);
                validate_opt_gateway(&gw, true)?;
                validate_opt_dns(&dns)?;
                let p = match &prefix {
                    Some(m) => parse_prefix(m, 128)?,
                    None => 128,
                };
                v6 = Some(Family { addrs: vec![(pos1, p)], gateway: gw, dns, is_dhcp: false });
            }
            break; // family2 末尾
        }
        // 4 元组组
        if rest.len() - i < 4 {
            return Err(format!(
                "incomplete 4-tuple group (need 4 tokens, got {}); for IP+routes/policy, family1 must be 4 tokens with '' for empty gw/dns",
                rest.len() - i
            )
            .into());
        }
        let g0 = rest[i].clone();
        let g1 = rest[i + 1].clone();
        let g2 = rest[i + 2].clone();
        let g3 = rest[i + 3].clone();

        if g2.is_empty() && g3.is_empty() {
            // 额外地址:addr mask '' ''
            if family1_is_v6 {
                if v6.as_ref().map(|f| f.is_dhcp).unwrap_or(false) {
                    return Err("cannot add static address to a dhcp family".into());
                }
                validate_ip(&g0, true)?;
                let p = parse_prefix(&g1, 128)?;
                v6.as_mut().unwrap().addrs.push((g0, p));
            } else {
                if v4.as_ref().map(|f| f.is_dhcp).unwrap_or(false) {
                    return Err("cannot add static address to a dhcp family".into());
                }
                validate_ip(&g0, false)?;
                let p = mask_to_prefix_checked(&g1, 32)?;
                v4.as_mut().unwrap().addrs.push((g0, p));
            }
            i += 4;
        } else if is_dotted_quad(&g3) {
            // 策略:from from_mask to to_mask [table](5 元组,table 可省;to_mask 强制点分)
            if g2.is_empty() {
                return Err(
                    "policy 'to' must not be empty; for a route use 'to to_mask via table'".into(),
                );
            }
            validate_ip(&g0, false)?;
            validate_ip(&g2, false)?;
            let from_prefix = mask_to_prefix_checked(&g1, 32)?;
            let to_prefix = mask_to_prefix_checked(&g3, 32)?;
            let from = (g0, from_prefix);
            let to = (g2, to_prefix);
            let g4 = rest.get(i + 4).cloned().unwrap_or_default();
            let (table, advance) = if !g4.is_empty() && is_table_token(&g4) {
                (Some(g4), 5)
            } else {
                (None, 4)
            };
            policies.push(Policy { from: Some(from), to: Some(to), table });
            i += advance;
        } else if g3.is_empty() || g3.parse::<u32>().is_ok() || is_table_name(&g3) {
            // 路由:to to_mask via table(via 可空=直连路由)
            validate_ip(&g0, false)?;
            let to_prefix = mask_to_prefix_checked(&g1, 32)?;
            let via = if g2.is_empty() {
                None
            } else {
                validate_ip(&g2, false)?;
                Some(g2)
            };
            routes.push(Route {
                to: g0,
                to_prefix,
                via,
                table: if g3.is_empty() { None } else { Some(g3) },
            });
            i += 4;
        } else {
            return Err(format!(
                "cannot classify group (pos4 '{}' is neither dotted mask nor table)",
                g3
            )
            .into());
        }
    }

    // 4-token 策略(无显式 table)仅在恰好 1 条路由时共享其 table;否则需显式第 5 token
    for p in policies.iter_mut() {
        if p.table.is_none() {
            p.table = match routes.len() {
                1 => {
                    let t = routes[0].table.clone();
                    if t.is_none() {
                        return Err(
                            "policy needs a table: the single route has no table; provide policy's 5th token".into(),
                        );
                    }
                    t
                }
                0 => return Err(
                    "policy needs a table: no route to share; provide policy's 5th token".into(),
                ),
                _ => return Err(
                    "policy needs explicit table (5th token): multiple routes present".into(),
                ),
            };
        }
    }

    Ok(Config {
        net_device: net_device.to_string(),
        family1_is_v6,
        v4,
        v6,
        routes,
        policies,
        dry_run: false,
    })
}

// ============ 解析辅助 ============

fn looks_like_ipv6(s: &str) -> bool {
    s.contains(':')
}
fn is_dhcp_token(s: &str) -> bool {
    let l = s.to_lowercase();
    l == "dhcp" || l == "auto"
}
fn jumps_to_family2(t: &str) -> bool {
    looks_like_ipv6(t) || is_dhcp_token(t)
}
/// 4 段点分八位组(255.255.255.0 或 192.168.3.0 等)
fn is_dotted_quad(s: &str) -> bool {
    let parts: Vec<&str> = s.split('.').collect();
    parts.len() == 4 && parts.iter().all(|p| p.parse::<u8>().is_ok())
}
/// 合法路由表名(非点分、非数字、非空、非 v6/dhcp)
fn is_table_name(s: &str) -> bool {
    !s.is_empty()
        && !is_dotted_quad(s)
        && !looks_like_ipv6(s)
        && !is_dhcp_token(s)
        && s.parse::<u32>().is_err()
        && s.chars().all(|c| c.is_alphanumeric() || c == '_' || c == '-')
}
/// 合法 table token(数字 id 或表名),用于策略第 5 token 识别
fn is_table_token(s: &str) -> bool {
    s.parse::<u32>().is_ok() || is_table_name(s)
}

/// 合法 IPv4 地址(4 段 0-255)
fn is_valid_ipv4(s: &str) -> bool {
    let parts: Vec<&str> = s.split('.').collect();
    parts.len() == 4 && parts.iter().all(|p| !p.is_empty() && p.parse::<u32>().map(|v| v <= 255).unwrap_or(false))
}
/// 合法 IPv6 地址(用 std::net 解析)
fn is_valid_ipv6(s: &str) -> bool {
    s.parse::<std::net::Ipv6Addr>().is_ok()
}

/// 填充 family1 可选槽(netmask/gateway/dns),返回 (nm,gw,dns,jumped_to_f2)
fn fill_family1_optional(
    rest: &[String],
    i: &mut usize,
    family1_is_v4: bool,
) -> (Option<String>, Option<String>, Option<String>, bool) {
    let mut slots: [Option<String>; 3] = [None, None, None];
    for idx in 0..3 {
        match rest.get(*i) {
            None => break,
            Some(v) if v.is_empty() => {
                *i += 1;
            }
            Some(v) => {
                if family1_is_v4 && jumps_to_family2(v) {
                    return (slots[0].clone(), slots[1].clone(), slots[2].clone(), true);
                }
                slots[idx] = Some(v.clone());
                *i += 1;
            }
        }
    }
    (slots[0].clone(), slots[1].clone(), slots[2].clone(), false)
}

/// 填充 family2(IPv6)4 槽
fn fill_family2(
    rest: &[String],
    i: &mut usize,
    ipv6: &mut Option<String>,
    ipv6_prefix: &mut Option<String>,
    ipv6_gateway: &mut Option<String>,
    ipv6_dns: &mut Option<String>,
) {
    let mut slots = [ipv6, ipv6_prefix, ipv6_gateway, ipv6_dns];
    let mut idx = *i;
    for slot in slots.iter_mut() {
        **slot = match rest.get(idx) {
            None => None,
            Some(v) if v.is_empty() => {
                idx += 1;
                None
            }
            Some(v) => {
                idx += 1;
                Some(v.clone())
            }
        };
    }
    *i = idx;
}

/// 读 3 个槽(4 元组里 family1/family2 的 mask/prefix、gw、dns),''→None,EOF→None
fn read_3slots(rest: &[String], i: &mut usize) -> (Option<String>, Option<String>, Option<String>) {
    let mut out: [Option<String>; 3] = [None, None, None];
    for idx in 0..3 {
        out[idx] = match rest.get(*i) {
            None => None,
            Some(v) if v.is_empty() => {
                *i += 1;
                None
            }
            Some(v) => {
                *i += 1;
                Some(v.clone())
            }
        };
    }
    (out[0].clone(), out[1].clone(), out[2].clone())
}

// ============ 掩码/前缀转换(带校验)============

/// 掩码或前缀 → 前缀(校验)。纯数字 0-32 直接当前缀;点分掩码须 4 段且连续;否则 Err。
fn mask_to_prefix_checked(mask: &str, max: u8) -> Result<u8, String> {
    // 纯数字前缀
    if let Ok(p) = mask.parse::<u32>() {
        if p <= max as u32 {
            return Ok(p as u8);
        }
        return Err(format!("prefix '{}' out of range (0-{})", mask, max));
    }
    // 点分掩码
    let parts: Vec<&str> = mask.split('.').collect();
    if parts.len() != 4 {
        return Err(format!("invalid netmask '{}': not a prefix nor dotted mask", mask));
    }
    let mut bits = [0u8; 4];
    for (k, p) in parts.iter().enumerate() {
        match p.parse::<u32>() {
            Ok(v) if v <= 255 => bits[k] = v as u8,
            _ => return Err(format!("invalid netmask '{}': octet out of range", mask)),
        }
    }
    let u32mask = ((bits[0] as u32) << 24) | ((bits[1] as u32) << 16) | ((bits[2] as u32) << 8) | (bits[3] as u32);
    // 连续 1 前缀:mask == !mask >> 1 的掩码形式。即 (mask + (mask & -mask)) == 0(全 1 后接全 0)
    if u32mask == 0 {
        return Ok(0);
    }
    // 合法网络掩码:从高位连续 1,然后连续 0。等价于 (mask | (mask-1)) == 0xFFFFFFFF
    if (u32mask | (u32mask.wrapping_sub(1))) != 0xFFFFFFFF {
        return Err(format!("invalid netmask '{}': non-contiguous mask", mask));
    }
    Ok(u32mask.count_ones() as u8)
}

/// IPv4/IPv6 前缀(纯数字)校验
fn parse_prefix(s: &str, max: u8) -> Result<u8, String> {
    match s.parse::<u32>() {
        Ok(p) if p <= max as u32 => Ok(p as u8),
        Ok(p) => Err(format!("prefix '{}' out of range (0-{})", p, max)),
        Err(_) => Err(format!("invalid prefix '{}': not a number", s)),
    }
}

/// 校验 IP 地址(按族),返回 Err 描述
fn validate_ip(s: &str, is_v6: bool) -> Result<(), String> {
    if s.contains('/') {
        return Err(format!("invalid address '{}': must not contain '/' (set prefix separately)", s));
    }
    let ok = if is_v6 { is_valid_ipv6(s) } else { is_valid_ipv4(s) };
    if ok {
        Ok(())
    } else {
        Err(format!("invalid {} address '{}'", if is_v6 { "IPv6" } else { "IPv4" }, s))
    }
}

/// 校验可选网关(空则跳过);is_v6 决定族
fn validate_opt_gateway(opt: &Option<String>, is_v6: bool) -> Result<(), String> {
    match opt {
        Some(s) if !s.is_empty() => validate_ip(s, is_v6),
        _ => Ok(()),
    }
}

/// 校验可选 DNS(空则跳过);可为 IPv4 或 IPv6
fn validate_opt_dns(opt: &Option<String>) -> Result<(), String> {
    match opt {
        Some(s) if !s.is_empty() => {
            if is_valid_ipv4(s) || is_valid_ipv6(s) {
                Ok(())
            } else {
                Err(format!("invalid DNS server '{}'", s))
            }
        }
        _ => Ok(()),
    }
}

// ============ main ============

#[derive(Debug)]
enum NetManager {
    Netplan,
    NetworkManager,
    SystemdNetworkd,
    Unknown,
}

fn main() {
    let cfg = match Config::parse() {
        Ok(c) => c,
        Err(e) => {
            eprintln!("Error: {}", e);
            eprintln!(
                "\nUsage: {} [--dry-run|-n] <net_device> <ip|dhcp> <netmask> [gw] [dns] ...\n  IP-only: old trailing-optional syntax (compatible). IP+routes/policy/extras: 4-tuple groups.",
                env::args().next().unwrap_or("bm_set_ip".into())
            );
            eprintln!("\nExamples:");
            eprintln!("  DHCP IPv4:      bm_set_ip eth0 dhcp");
            eprintln!("  Static IPv4:    bm_set_ip eth0 192.168.1.100 24 192.168.1.1 8.8.8.8");
            eprintln!("  Multi-addr+route(4-tuple): bm_set_ip eth0 192.168.1.100 24 192.168.1.1 8.8.8.8  192.168.1.101 24 '' ''  192.168.2.0 24 192.168.1.1 100");
            eprintln!("  Route+policy(4-tuple):     bm_set_ip eth0 192.168.1.100 24 '' ''  192.168.2.0 24 192.168.1.1 100  10.0.0.0 24 192.168.3.0 255.255.255.0 [table]");
            eprintln!("  Multi-policy(5-tuple):     bm_set_ip eth0 192.168.1.100 24 '' ''  192.168.2.0 24 192.168.1.1 100  10.0.0.0 24 192.168.3.0 255.255.255.0 100  10.1.0.0 24 192.168.4.0 255.255.255.0 200");
            eprintln!("  Dry-run:        bm_set_ip --dry-run eth0 192.168.1.100 24");
            exit(1);
        }
    };

    if cfg.dry_run {
        print_analyzed_config(&cfg);
        return;
    }

    if !is_root() {
        let exe = env::current_exe().unwrap();
        let argv: Vec<String> = env::args().skip(1).collect();
        let status = Command::new("sudo")
            .arg(exe)
            .args(&argv)
            .status()
            .expect("failed to execute sudo");
        exit(status.code().unwrap_or(1));
    }
    println!("bm_set_ip version: {}", concat!(env!("GIT_TAG_COMMIT")));

    let net_manager = detect_net_manager();
    match net_manager {
        NetManager::Netplan => {
            println!("[INFO] Using netplan for network configuration");
            configure_with_netplan(&cfg);
        }
        NetManager::NetworkManager => {
            println!("[INFO] Using NetworkManager (nmcli) for network configuration");
            configure_with_nmcli(&cfg);
        }
        NetManager::SystemdNetworkd => {
            println!("[INFO] Using systemd-networkd for network configuration");
            configure_with_networkd(&cfg);
        }
        NetManager::Unknown => {
            eprintln!("[ERROR] Could not detect a supported network manager!");
            eprintln!("[INFO] Trying to configure IP manually using ip command");
            configure_with_ip(&cfg);
        }
    }
}

// ============ dry-run 输出 ============

fn print_analyzed_config(cfg: &Config) {
    println!("## bm_set_ip dry-run config begin");
    println!("net_device={}", cfg.net_device);
    println!("family1_is_v6={}", cfg.family1_is_v6);

    fn fam_lines(label: &str, f: Option<&Family>) {
        match f {
            Some(f) => {
                let addrs: Vec<String> = f.addrs.iter().map(|(a, p)| format!("{}/{}", a, p)).collect();
                println!("{}.present=true", label);
                println!("{}.is_dhcp={}", label, f.is_dhcp);
                println!("{}.addrs={}", label, addrs.join(","));
                println!("{}.gateway={}", label, f.gateway.as_deref().unwrap_or(""));
                println!("{}.dns={}", label, f.dns.as_deref().unwrap_or(""));
            }
            None => {
                println!("{}.present=false", label);
                println!("{}.is_dhcp=false", label);
                println!("{}.addrs=", label);
                println!("{}.gateway=", label);
                println!("{}.dns=", label);
            }
        }
    }
    fam_lines("v4", cfg.v4.as_ref());
    fam_lines("v6", cfg.v6.as_ref());

    println!("routes.count={}", cfg.routes.len());
    for (idx, r) in cfg.routes.iter().enumerate() {
        println!("routes[{}].to={}", idx, r.to);
        println!("routes[{}].to_prefix={}", idx, r.to_prefix);
        println!("routes[{}].via={}", idx, r.via.as_deref().unwrap_or(""));
        println!("routes[{}].table={}", idx, r.table.as_deref().unwrap_or(""));
    }

    println!("policies.count={}", cfg.policies.len());
    for (idx, p) in cfg.policies.iter().enumerate() {
        println!("policies[{}].from={}", idx, p.from.as_ref().map(|(n, _)| n.as_str()).unwrap_or(""));
        println!("policies[{}].from_prefix={}", idx, p.from.as_ref().map(|(_, px)| *px).unwrap_or(0));
        println!("policies[{}].to={}", idx, p.to.as_ref().map(|(n, _)| n.as_str()).unwrap_or(""));
        println!("policies[{}].to_prefix={}", idx, p.to.as_ref().map(|(_, px)| *px).unwrap_or(0));
        println!("policies[{}].table={}", idx, p.table.as_deref().unwrap_or(""));
    }
    println!("## bm_set_ip dry-run config end");
}

// ============ 通用辅助 ============

fn is_command_exists(cmd: &str) -> bool {
    if let Some(paths) = std::env::var_os("PATH") {
        for path in std::env::split_paths(&paths) {
            if path.join(cmd).is_file() {
                return true;
            }
        }
    }
    false
}

fn extra_default_routes(current_dev: &str) -> Vec<String> {
    let mut others = Vec::new();
    if let Ok(output) = Command::new("ip").args(["route", "show", "default"]).output() {
        let routes = String::from_utf8_lossy(&output.stdout);
        for line in routes.lines() {
            if line.starts_with("default ") && !line.contains(&format!("dev {}", current_dev)) {
                others.push(line.to_string());
            }
        }
    }
    others
}

fn warn_extra_routes(current_dev: &str) {
    let extra = extra_default_routes(current_dev);
    if !extra.is_empty() {
        eprintln!("[WARNING] system has extra default routes on other devices:");
        for r in &extra {
            eprintln!("[WARNING]     {}", r);
        }
    }
}

fn detect_net_manager() -> NetManager {
    // netplan 后端依赖 /etc/netplan/01-netcfg.yaml;命令存在但无 yaml 则跳过(避免直接 exit)
    if is_command_exists("netplan") && fs::File::open("/etc/netplan/01-netcfg.yaml").is_ok() {
        return NetManager::Netplan;
    }
    if is_command_exists("nmcli") {
        let status = Command::new("systemctl").arg("is-active").arg("NetworkManager").output();
        if let Ok(output) = status {
            if output.stdout == b"active\n" {
                return NetManager::NetworkManager;
            }
        }
    }
    let status = Command::new("systemctl").arg("is-active").arg("systemd-networkd").output();
    if let Ok(output) = status {
        if output.stdout == b"active\n" {
            return NetManager::SystemdNetworkd;
        }
    }
    NetManager::Unknown
}

fn is_root() -> bool {
    unsafe { libc::geteuid() == 0 }
}

fn get_or_create_mapping<'a>(map: &'a mut Mapping, key: &str) -> &'a mut Mapping {
    let entry = map
        .entry(Value::String(key.to_string()))
        .or_insert_with(|| Value::Mapping(Mapping::new()));
    if !entry.is_mapping() {
        *entry = Value::Mapping(Mapping::new());
    }
    entry
        .as_mapping_mut()
        .expect(&format!("[ERROR] '{}' is not a mapping", key))
}

// ============ netplan 后端 ============

fn configure_with_netplan(cfg: &Config) {
    let file_path = "/etc/netplan/01-netcfg.yaml";
    if fs::File::open(file_path).is_err() {
        eprintln!("[ERROR] Cannot read {}", file_path);
        std::process::exit(1);
    }
    let content = fs::read_to_string(file_path).expect("[ERROR] Cannot read netplan config file");
    let mut doc: serde_yaml::Value = match serde_yaml::from_str(&content) {
        Ok(doc) => doc,
        Err(e) => {
            eprintln!("[ERROR] YAML parsing failed: {}\nError location: {:?}", e, e.location());
            panic!("[ERROR] YAML parsing aborted");
        }
    };

    let network_map = doc.as_mapping_mut().unwrap();
    let ethernets_map = get_or_create_mapping(network_map, "network");
    let ethernets = get_or_create_mapping(ethernets_map, "ethernets");

    let mut dev_cfg = serde_yaml::Mapping::new();
    let mut addresses_seq: Vec<Value> = Vec::new();
    let mut routes_seq: Vec<Value> = Vec::new();

    // IPv4
    if let Some(v4f) = &cfg.v4 {
        if v4f.is_dhcp {
            warn_extra_routes(&cfg.net_device);
            dev_cfg.insert(Value::String("dhcp4".into()), Value::Bool(true));
        } else {
            dev_cfg.insert(Value::String("dhcp4".into()), Value::Bool(false));
            for (a, p) in &v4f.addrs {
                addresses_seq.push(Value::String(format!("{}/{}", a, p)));
            }
            if let Some(gw) = &v4f.gateway {
                if !gw.is_empty() {
                    warn_extra_routes(&cfg.net_device);
                    let mut r = Mapping::new();
                    r.insert(Value::String("to".into()), Value::String("0.0.0.0/0".into()));
                    r.insert(Value::String("via".into()), Value::String(gw.clone()));
                    routes_seq.push(Value::Mapping(r));
                }
            }
        }
    }

    // IPv6
    if let Some(v6f) = &cfg.v6 {
        if v6f.is_dhcp {
            dev_cfg.insert(Value::String("dhcp6".into()), Value::Bool(true));
        } else {
            dev_cfg.insert(Value::String("dhcp6".into()), Value::Bool(false));
            for (a, p) in &v6f.addrs {
                addresses_seq.push(Value::String(format!("{}/{}", a, p)));
            }
            if let Some(gw) = &v6f.gateway {
                if !gw.is_empty() {
                    let mut r = Mapping::new();
                    r.insert(Value::String("to".into()), Value::String("::/0".into()));
                    r.insert(Value::String("via".into()), Value::String(gw.clone()));
                    routes_seq.push(Value::Mapping(r));
                }
            }
        }
    }

    // 静态路由
    for r in &cfg.routes {
        let mut m = Mapping::new();
        m.insert(Value::String("to".into()), Value::String(format!("{}/{}", r.to, r.to_prefix)));
        if let Some(via) = &r.via {
            m.insert(Value::String("via".into()), Value::String(via.clone()));
        }
        if let Some(t) = &r.table {
            m.insert(Value::String("table".into()), Value::String(t.clone()));
        }
        routes_seq.push(Value::Mapping(m));
    }
    if !addresses_seq.is_empty() {
        dev_cfg.insert(Value::String("addresses".into()), Value::Sequence(addresses_seq));
    }
    if !routes_seq.is_empty() {
        dev_cfg.insert(Value::String("routes".into()), Value::Sequence(routes_seq));
    }

    // 策略(多条)
    if !cfg.policies.is_empty() {
        let mut policy_seq: Vec<Value> = Vec::new();
        for p in &cfg.policies {
            if let Some((n, px)) = &p.from {
                let mut m = Mapping::new();
                m.insert(Value::String("from".into()), Value::String(format!("{}/{}", n, px)));
                if let Some(t) = &p.table {
                    m.insert(Value::String("table".into()), Value::String(t.clone()));
                }
                policy_seq.push(Value::Mapping(m));
            }
            if let Some((n, px)) = &p.to {
                let mut m = Mapping::new();
                m.insert(Value::String("to".into()), Value::String(format!("{}/{}", n, px)));
                if let Some(t) = &p.table {
                    m.insert(Value::String("table".into()), Value::String(t.clone()));
                }
                policy_seq.push(Value::Mapping(m));
            }
        }
        if !policy_seq.is_empty() {
            dev_cfg.insert(Value::String("routing-policy".into()), Value::Sequence(policy_seq));
        }
    }

    // DNS
    let mut dns_list = Vec::new();
    if let Some(v4f) = &cfg.v4 {
        if let Some(d) = &v4f.dns {
            if !d.is_empty() {
                dns_list.push(Value::String(d.clone()));
            }
        }
    }
    if let Some(v6f) = &cfg.v6 {
        if let Some(d) = &v6f.dns {
            if !d.is_empty() {
                dns_list.push(Value::String(d.clone()));
            }
        }
    }
    if !dns_list.is_empty() {
        let mut dns_map = serde_yaml::Mapping::new();
        dns_map.insert(Value::String("addresses".into()), Value::Sequence(dns_list));
        dev_cfg.insert(Value::String("nameservers".into()), Value::Mapping(dns_map));
    }

    dev_cfg.insert(Value::String("optional".into()), Value::Bool(true));
    println!("[INFO] Add config: {:?}", dev_cfg);

    ethernets.insert(Value::String(cfg.net_device.clone()), Value::Mapping(dev_cfg));

    let new_content = serde_yaml::to_string(&doc).unwrap();
    fs::write(file_path, new_content).expect("Failed to write netplan config");

    // netplan apply 在某些校验失败(如 conflicting default route)时退出码仍为 0,
    // 故除退出码外还需检查 stderr 是否含 Error/Conflicting。
    let out = Command::new("netplan").arg("apply").output();
    match out {
        Ok(o) => {
            let stderr = String::from_utf8_lossy(&o.stderr);
            let bad = !o.status.success()
                || stderr.lines().any(|l| l.starts_with("Error") || l.contains("Conflicting default route"));
            if bad {
                eprintln!("[ERROR] Failed to apply netplan configuration");
                for l in stderr.lines().filter(|l| l.starts_with("Error") || l.contains("Conflicting")) {
                    eprintln!("[ERROR]     {}", l);
                }
            } else {
                println!("[INFO] Netplan configuration applied successfully");
            }
        }
        Err(_) => eprintln!("[ERROR] Could not run netplan"),
    }
}

/// 解析 /etc/iproute2/rt_tables,返回 表名→数字id 的映射
fn load_rt_tables() -> std::collections::HashMap<String, u32> {
    let mut map = std::collections::HashMap::new();
    if let Ok(content) = fs::read_to_string("/etc/iproute2/rt_tables") {
        for line in content.lines() {
            let line = line.trim();
            if line.is_empty() || line.starts_with('#') {
                continue;
            }
            let parts: Vec<&str> = line.split_whitespace().collect();
            if parts.len() >= 2 {
                if let Ok(id) = parts[0].parse::<u32>() {
                    let name = parts[1].to_string();
                    map.insert(name, id);
                }
            }
        }
    }
    map
}

/// 表名 → 数字 id(用于 nmcli 后端)
/// 先尝试解析数字,再查 rt_tables,都不行则自动分配空闲 id
/// 返回值: (id, 是否新分配)
fn resolve_table_id(t: &str, name_to_id: &std::collections::HashMap<String, u32>) -> (u32, bool) {
    // 直接数字
    if let Ok(n) = t.parse::<u32>() {
        return (n, false);
    }
    // 查 rt_tables
    if let Some(n) = name_to_id.get(t) {
        return (*n, false);
    }
    // 自动分配: 从 100 开始找第一个没被占用的 id
    let mut alloc = 100u32;
    while name_to_id.values().any(|v| *v == alloc) {
        alloc += 1;
    }
    (alloc, true)
}

// ============ nmcli 后端 ============

fn configure_with_nmcli(cfg: &Config) {
    let con_name = format!("static-{}", &cfg.net_device);
    let _ = Command::new("nmcli").args(["con", "delete", &con_name]).output();

    let mut add_args: Vec<String> = vec![
        "con".into(), "add".into(), "type".into(), "ethernet".into(),
        "ifname".into(), cfg.net_device.clone().into(),
        "con-name".into(), con_name.clone().into(),
        "connection.autoconnect-priority".into(), "10".into(),
    ];

    if let Some(v4f) = &cfg.v4 {
        if v4f.is_dhcp {
            warn_extra_routes(&cfg.net_device);
            add_args.push("ipv4.method".into());
            add_args.push("auto".into());
        } else if !v4f.addrs.is_empty() {
            let addrs: Vec<String> = v4f.addrs.iter().map(|(a, p)| format!("{}/{}", a, p)).collect();
            add_args.push("ipv4.addresses".into());
            add_args.push(addrs.join(","));
            add_args.push("ipv4.method".into());
            add_args.push("manual".into());
            if let Some(gw) = &v4f.gateway {
                if !gw.is_empty() {
                    warn_extra_routes(&cfg.net_device);
                    add_args.push("ipv4.gateway".into());
                    add_args.push(gw.clone());
                }
            }
            if let Some(dns) = &v4f.dns {
                if !dns.is_empty() {
                    add_args.push("ipv4.dns".into());
                    add_args.push(dns.clone());
                }
            }
        }
    }
    if let Some(v6f) = &cfg.v6 {
        if v6f.is_dhcp {
            add_args.push("ipv6.method".into());
            add_args.push("auto".into());
        } else if !v6f.addrs.is_empty() {
            let addrs: Vec<String> = v6f.addrs.iter().map(|(a, p)| format!("{}/{}", a, p)).collect();
            add_args.push("ipv6.addresses".into());
            add_args.push(addrs.join(","));
            add_args.push("ipv6.method".into());
            add_args.push("manual".into());
            if let Some(gw) = &v6f.gateway {
                if !gw.is_empty() {
                    add_args.push("ipv6.gateway".into());
                    add_args.push(gw.clone());
                }
            }
            if let Some(dns) = &v6f.dns {
                if !dns.is_empty() {
                    add_args.push("ipv6.dns".into());
                    add_args.push(dns.clone());
                }
            }
        }
    }
    // 静态路由(nmcli ipv4.routes:逗号分隔多条;字段用空格;table 用 table=N)
    if !cfg.routes.is_empty() {
        let entries: Vec<String> = cfg.routes.iter().map(|r| {
            let mut e = format!("{}/{}", r.to, r.to_prefix);
            if let Some(via) = &r.via {
                e.push_str(&format!(" {}", via));
            }
            if let Some(t) = &r.table {
                e.push_str(&format!(" table={}", t));
            }
            e
        }).collect();
        add_args.push("ipv4.routes".into());
        add_args.push(entries.join(","));
    }
    // 策略(nmcli ipv4.routing-rules:逗号分隔,需固定 priority,table 仅数字 id)
    // 若表名为非数字,则从 /etc/iproute2/rt_tables 查找映射
    if !cfg.policies.is_empty() {
        let name_to_id = load_rt_tables();
        let mut rules: Vec<String> = Vec::new();
        let mut prio = 32760u32; // 从 32760 起递减,避开 main/default
        for p in &cfg.policies {
            let t = p.table.as_deref().unwrap_or("");
            if t.is_empty() {
                continue;
            }
            let tid = match t.parse::<u32>() {
                Ok(n) => n,
                Err(_) => {
                    let (id, alloced) = resolve_table_id(t, &name_to_id);
                    if alloced {
                        eprintln!("[INFO] nmcli: auto-assigned table id {} for name '{}'", id, t);
                    } else {
                        eprintln!("[INFO] nmcli: resolved table name '{}' → id {}", t, id);
                    }
                    id
                }
            };
            if let Some((n, px)) = &p.from {
                rules.push(format!("priority {} from {}/{} table {}", prio, n, px, tid));
            }
            if let Some((n, px)) = &p.to {
                rules.push(format!("priority {} to {}/{} table {}", prio, n, px, tid));
            }
            if prio > 100 { prio -= 1; }
        }
        if !rules.is_empty() {
            add_args.push("ipv4.routing-rules".into());
            add_args.push(rules.join(","));
        }
    }

    let status = Command::new("nmcli").args(&add_args).status();
    if let Ok(s) = status {
        if s.success() {
            let _ = Command::new("nmcli").args(["con", "up", &con_name]).status();
            println!("[INFO] nmcli configuration applied successfully");
        } else {
            eprintln!("[ERROR] Failed to apply nmcli configuration");
        }
    } else {
        eprintln!("[ERROR] Could not run nmcli");
    }
}

// ============ systemd-networkd 后端 ============

fn configure_with_networkd(cfg: &Config) {
    let file_path = format!("/etc/systemd/network/10-{}.network", cfg.net_device);
    let mut file = fs::File::create(&file_path).expect("[ERROR] Failed to create networkd config file");

    writeln!(file, "[Match]").unwrap();
    writeln!(file, "Name={}", cfg.net_device).unwrap();
    writeln!(file).unwrap();
    writeln!(file, "[Network]").unwrap();

    if let Some(v4f) = &cfg.v4 {
        if v4f.is_dhcp {
            writeln!(file, "DHCP=ipv4").unwrap();
        } else {
            for (a, p) in &v4f.addrs {
                writeln!(file, "Address={}/{}", a, p).unwrap();
            }
            if let Some(gw) = &v4f.gateway {
                if !gw.is_empty() {
                    writeln!(file, "Gateway={}", gw).unwrap();
                }
            }
        }
    }
    if let Some(v6f) = &cfg.v6 {
        if v6f.is_dhcp {
            writeln!(file, "DHCP=ipv6").unwrap();
        } else {
            for (a, p) in &v6f.addrs {
                writeln!(file, "Address={}/{}", a, p).unwrap();
            }
            if let Some(gw) = &v6f.gateway {
                if !gw.is_empty() {
                    writeln!(file, "Gateway={}", gw).unwrap();
                }
            }
        }
    }
    let mut dns_list = Vec::new();
    if let Some(v4f) = &cfg.v4 {
        if let Some(d) = &v4f.dns { if !d.is_empty() { dns_list.push(d.clone()); } }
    }
    if let Some(v6f) = &cfg.v6 {
        if let Some(d) = &v6f.dns { if !d.is_empty() { dns_list.push(d.clone()); } }
    }
    if !dns_list.is_empty() {
        writeln!(file, "DNS={}", dns_list.join(" ")).unwrap();
    }

    for r in &cfg.routes {
        writeln!(file).unwrap();
        writeln!(file, "[Route]").unwrap();
        writeln!(file, "Destination={}/{}", r.to, r.to_prefix).unwrap();
        if let Some(via) = &r.via {
            writeln!(file, "Gateway={}", via).unwrap();
        }
        if let Some(t) = &r.table {
            writeln!(file, "Table={}", t).unwrap();
        }
    }
    for p in &cfg.policies {
        if let Some(t) = &p.table {
            if let Some((n, px)) = &p.from {
                writeln!(file).unwrap();
                writeln!(file, "[RoutingPolicyRule]").unwrap();
                writeln!(file, "From={}/{}", n, px).unwrap();
                writeln!(file, "Table={}", t).unwrap();
            }
            if let Some((n, px)) = &p.to {
                writeln!(file).unwrap();
                writeln!(file, "[RoutingPolicyRule]").unwrap();
                writeln!(file, "To={}/{}", n, px).unwrap();
                writeln!(file, "Table={}", t).unwrap();
            }
        }
    }

    println!("[INFO] Created systemd-networkd config at {}", file_path);
    // 用 networkctl reload + reconfigure 仅重载该设备,避免 restart 波及其他网口
    let _ = Command::new("networkctl").arg("reload").status();
    let rc = Command::new("networkctl").arg("reconfigure").arg(&cfg.net_device).status();
    let ok = match rc {
        Ok(s) => s.success(),
        Err(_) => {
            eprintln!("[WARNING] networkctl unavailable, falling back to restart systemd-networkd");
            Command::new("systemctl").args(["restart", "systemd-networkd"]).status().map(|s| s.success()).unwrap_or(false)
        }
    };
    if ok {
        println!("[INFO] systemd-networkd configuration applied successfully");
    } else {
        eprintln!("[ERROR] Failed to apply systemd-networkd configuration");
    }
}

// ============ ip 兜底后端 ============

fn configure_with_ip(cfg: &Config) {
    let any_dhcp = cfg.v4.as_ref().map(|f| f.is_dhcp).unwrap_or(false)
        || cfg.v6.as_ref().map(|f| f.is_dhcp).unwrap_or(false);
    if any_dhcp {
        eprintln!("[ERROR] DHCP is not supported when using manual IP configuration");
        return;
    }

    // 执行 ip 命令,失败时打印 [WARNING](含 stderr),返回是否成功
    let run = |args: &[&str]| -> bool {
        let out = Command::new("ip").args(args).output();
        match out {
            Ok(o) => {
                if !o.status.success() {
                    let err = String::from_utf8_lossy(&o.stderr);
                    eprintln!("[WARNING] `ip {}` failed: {}", args.join(" "), err.trim_end());
                    false
                } else {
                    true
                }
            }
            Err(_) => {
                eprintln!("[ERROR] Could not run `ip {}`", args.join(" "));
                false
            }
        }
    };
    // flush 后立即 up,避免裸接口
    run(&["addr", "flush", "dev", &cfg.net_device]);
    run(&["link", "set", "dev", &cfg.net_device, "up"]);

    let mut addr_ok = 0;
    let mut addr_total = 0;
    if let Some(v4f) = &cfg.v4 {
        for (a, p) in &v4f.addrs {
            addr_total += 1;
            let spec = format!("{}/{}", a, p);
            if run(&["addr", "add", &spec, "dev", &cfg.net_device]) { addr_ok += 1; }
        }
        if let Some(gw) = &v4f.gateway {
            if !gw.is_empty() {
                // main 表默认路由:若已存在其他默认路由会失败(File exists),给明确提示
                if !run(&["route", "add", "default", "via", gw, "dev", &cfg.net_device]) {
                    eprintln!("[WARNING] default route via {} not added (another default route may exist in table main; use policy routing for multi-gateway)", gw);
                }
            }
        }
    }
    if let Some(v6f) = &cfg.v6 {
        for (a, p) in &v6f.addrs {
            addr_total += 1;
            let spec = format!("{}/{}", a, p);
            if run(&["addr", "add", &spec, "dev", &cfg.net_device]) { addr_ok += 1; }
        }
    }
    if addr_total > 0 && addr_ok == 0 {
        eprintln!("[ERROR] Failed to add any of the {} address(es) to {}", addr_total, cfg.net_device);
    }
    for r in &cfg.routes {
        let mut args: Vec<String> = vec!["route".into(), "add".into(), format!("{}/{}", r.to, r.to_prefix)];
        if let Some(via) = &r.via {
            args.push("via".into());
            args.push(via.clone());
        }
        args.push("dev".into());
        args.push(cfg.net_device.clone());
        if let Some(t) = &r.table {
            args.push("table".into());
            args.push(t.clone());
        }
        let refs: Vec<&str> = args.iter().map(|s| s.as_str()).collect();
        run(&refs);
    }
    for p in &cfg.policies {
        if let Some(t) = &p.table {
            if let Some((n, px)) = &p.from {
                let spec = format!("{}/{}", n, px);
                run(&["rule", "add", "from", &spec, "table", t]);
            }
            if let Some((n, px)) = &p.to {
                let spec = format!("{}/{}", n, px);
                run(&["rule", "add", "to", &spec, "table", t]);
            }
        }
    }

    // 确保 up
    run(&["link", "set", "dev", &cfg.net_device, "up"]);
    println!("[INFO] Manual IP configuration applied (addresses: {}/{})", addr_ok, addr_total);
}
