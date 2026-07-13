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
    force: bool,
}

impl Config {
    fn parse() -> Result<Self, lexopt::Error> {
        use lexopt::prelude::*;

        let mut positional: Vec<String> = Vec::new();
        let mut dry_run = false;
        let mut force = false;
        let mut parser = lexopt::Parser::from_env();
        while let Some(arg) = parser.next()? {
            match arg.clone() {
                Value(val) => positional.push(val.into_string()?),
                Long(name) if name == "dry-run" => dry_run = true,
                Long(name) if name == "force" => force = true,
                Long(name) if name == "help" => {
                    print_usage();
                    exit(0);
                }
                Short('n') => dry_run = true,
                Short('h') => {
                    print_usage();
                    exit(0);
                }
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
        cfg.force = force;
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
        force: false,
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
        // dhcp 单 token。若紧跟 3 个空槽('' '' '')则消费之(对齐 4 元组),
        // 否则不动(向后兼容 dhcp 直接接路由/策略/family2)。
        if rest.get(i).map(|s| s.is_empty()).unwrap_or(false)
            && rest.get(i + 1).map(|s| s.is_empty()).unwrap_or(false)
            && rest.get(i + 2).map(|s| s.is_empty()).unwrap_or(false)
        {
            i += 3;
        }
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
        force: false,
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

/// 合法 IPv4 地址(4 段 0-255,拒绝前导零)
fn is_valid_ipv4(s: &str) -> bool {
    let parts: Vec<&str> = s.split('.').collect();
    parts.len() == 4 && parts.iter().all(|p| {
        !p.is_empty()
            && (*p == "0" || !p.starts_with('0'))
            && p.parse::<u32>().map(|v| v <= 255).unwrap_or(false)
    })
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

fn print_usage() {
    eprintln!(
        "\nUsage: {} [--dry-run|-n] [--force] <net_device> <ip|dhcp> <netmask> [gw] [dns] ...\n  IP-only: old trailing-optional syntax (compatible). IP+routes/policy/extras: 4-tuple groups.\n  --force: allow ip-fallback to flush the device carrying the default route.",
        env::args().next().unwrap_or("bm_set_ip".into())
    );
    eprintln!("\nExamples:");
    eprintln!("  DHCP IPv4:      bm_set_ip eth0 dhcp");
    eprintln!("  Static IPv4:    bm_set_ip eth0 192.168.1.100 24 192.168.1.1 8.8.8.8");
    eprintln!("  Multi-addr+route(4-tuple): bm_set_ip eth0 192.168.1.100 24 192.168.1.1 8.8.8.8  192.168.1.101 24 '' ''  192.168.2.0 24 192.168.1.1 100");
    eprintln!("  Route+policy(4-tuple):     bm_set_ip eth0 192.168.1.100 24 '' ''  192.168.2.0 24 192.168.1.1 100  10.0.0.0 24 192.168.3.0 255.255.255.0 [table]");
    eprintln!("  Multi-policy(5-tuple):     bm_set_ip eth0 192.168.1.100 24 '' ''  192.168.2.0 24 192.168.1.1 100  10.0.0.0 24 192.168.3.0 255.255.255.0 100  10.1.0.0 24 192.168.4.0 255.255.255.0 200");
    eprintln!("  Dry-run:        bm_set_ip --dry-run eth0 192.168.1.100 24");
}

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
            print_usage();
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
    // B2:netplan 命令存在 且 /etc/netplan/ 下任一 *.yaml 存在
    if is_command_exists("netplan") {
        let has_yaml = fs::read_dir("/etc/netplan")
            .map(|entries| entries.flatten().any(|e| e.path().extension().map(|x| x == "yaml").unwrap_or(false)))
            .unwrap_or(false);
        if has_yaml {
            return NetManager::Netplan;
        }
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

fn get_or_create_mapping<'a>(map: &'a mut Mapping, key: &str) -> Result<&'a mut Mapping, String> {
    let entry = map
        .entry(Value::String(key.to_string()))
        .or_insert_with(|| Value::Mapping(Mapping::new()));
    if !entry.is_mapping() {
        *entry = Value::Mapping(Mapping::new());
    }
    entry
        .as_mapping_mut()
        .ok_or_else(|| format!("[ERROR] '{}' is not a mapping", key))
}

// ============ netplan 后端 ============

fn select_netplan_file() -> String {
    if let Ok(f) = std::env::var("BM_SET_IP_NETPLAN_FILE") {
        if !f.is_empty() {
            return f;
        }
    }
    let mut yamls: Vec<String> = Vec::new();
    if let Ok(entries) = fs::read_dir("/etc/netplan") {
        for e in entries.flatten() {
            let p = e.path();
            if p.extension().map(|x| x == "yaml").unwrap_or(false) {
                if let Some(name) = p.file_name().and_then(|s| s.to_str()) {
                    yamls.push(name.to_string());
                }
            }
        }
    }
    yamls.sort();
    if let Some(last) = yamls.last() {
        format!("/etc/netplan/{}", last)
    } else {
        eprintln!("[WARNING] no /etc/netplan/*.yaml found, falling back to 01-netcfg.yaml");
        "/etc/netplan/01-netcfg.yaml".to_string()
    }
}

fn netplan_render(cfg: &Config, existing_yaml: &str, target_file: &str) -> Result<String, String> {
    let _ = target_file;
    let mut doc: serde_yaml::Value = serde_yaml::from_str(existing_yaml)
        .map_err(|e| format!("YAML parsing failed: {}", e))?;
    let network_map = doc.as_mapping_mut().ok_or_else(|| "netplan yaml top-level is not a mapping".to_string())?;
    let ethernets_map = get_or_create_mapping(network_map, "network")?;
    let ethernets = get_or_create_mapping(ethernets_map, "ethernets")?;

    // B3:若设备已存在且为 mapping,在其上更新;否则新建
    let dev_key = Value::String(cfg.net_device.clone());
    let mut dev_cfg = match ethernets.get(&dev_key) {
        Some(Value::Mapping(m)) => m.clone(),
        _ => serde_yaml::Mapping::new(),
    };
    // 本工具管理的键(更新前移除,再按当前配置写入)
    for k in ["dhcp4", "dhcp6", "addresses", "routes", "routing-policy", "nameservers", "optional"] {
        dev_cfg.remove(Value::String(k.into()));
    }

    let mut addresses_seq: Vec<Value> = Vec::new();
    let mut routes_seq: Vec<Value> = Vec::new();

    if let Some(v4f) = &cfg.v4 {
        if v4f.is_dhcp {
            dev_cfg.insert(Value::String("dhcp4".into()), Value::Bool(true));
        } else {
            dev_cfg.insert(Value::String("dhcp4".into()), Value::Bool(false));
            for (a, p) in &v4f.addrs {
                addresses_seq.push(Value::String(format!("{}/{}", a, p)));
            }
            if let Some(gw) = &v4f.gateway {
                if !gw.is_empty() {
                    let mut r = Mapping::new();
                    r.insert(Value::String("to".into()), Value::String("0.0.0.0/0".into()));
                    r.insert(Value::String("via".into()), Value::String(gw.clone()));
                    routes_seq.push(Value::Mapping(r));
                }
            }
        }
    }
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
    // A3:from+to 同存 → 单个 routing-policy 项
    if !cfg.policies.is_empty() {
        let mut policy_seq: Vec<Value> = Vec::new();
        for p in &cfg.policies {
            let mut m = Mapping::new();
            if let Some((n, px)) = &p.from {
                m.insert(Value::String("from".into()), Value::String(format!("{}/{}", n, px)));
            }
            if let Some((n, px)) = &p.to {
                m.insert(Value::String("to".into()), Value::String(format!("{}/{}", n, px)));
            }
            if let Some(t) = &p.table {
                m.insert(Value::String("table".into()), Value::String(t.clone()));
            }
            if !m.is_empty() {
                policy_seq.push(Value::Mapping(m));
            }
        }
        if !policy_seq.is_empty() {
            dev_cfg.insert(Value::String("routing-policy".into()), Value::Sequence(policy_seq));
        }
    }
    let mut dns_list = Vec::new();
    if let Some(v4f) = &cfg.v4 {
        if let Some(d) = &v4f.dns { if !d.is_empty() { dns_list.push(Value::String(d.clone())); } }
    }
    if let Some(v6f) = &cfg.v6 {
        if let Some(d) = &v6f.dns { if !d.is_empty() { dns_list.push(Value::String(d.clone())); } }
    }
    if !dns_list.is_empty() {
        let mut dns_map = serde_yaml::Mapping::new();
        dns_map.insert(Value::String("addresses".into()), Value::Sequence(dns_list));
        dev_cfg.insert(Value::String("nameservers".into()), Value::Mapping(dns_map));
    }
    dev_cfg.insert(Value::String("optional".into()), Value::Bool(true));

    ethernets.insert(dev_key, Value::Mapping(dev_cfg));
    serde_yaml::to_string(&doc).map_err(|e| format!("YAML serialize failed: {}", e))
}

fn configure_with_netplan(cfg: &Config) {
    let file_path = select_netplan_file();
    let content = match fs::read_to_string(&file_path) {
        Ok(c) => c,
        Err(_) => {
            eprintln!("[ERROR] Cannot read {}", file_path);
            std::process::exit(1);
        }
    };

    // C5:与 networkd/nmcli/ip 对齐,多默认网关时告警
    if let Some(v4f) = &cfg.v4 {
        if !v4f.is_dhcp {
            if let Some(gw) = &v4f.gateway {
                if !gw.is_empty() {
                    warn_extra_routes(&cfg.net_device);
                }
            }
        }
    }

    let new_content = match netplan_render(cfg, &content, &file_path) {
        Ok(s) => s,
        Err(e) => {
            eprintln!("[ERROR] {}", e);
            std::process::exit(1);
        }
    };

    // B1:写前备份
    let bak = format!("{}.bm_set_ip.bak", file_path);
    let _ = fs::copy(&file_path, &bak);

    fs::write(&file_path, &new_content).expect("Failed to write netplan config");
    println!("[INFO] Wrote {} (backup at {})", file_path, bak);

    let out = Command::new("netplan").arg("apply").output();
    let apply_ok = match out {
        Ok(o) => {
            let stderr = String::from_utf8_lossy(&o.stderr);
            let bad = !o.status.success()
                || stderr.lines().any(|l| l.starts_with("Error") || l.contains("Conflicting default route"));
            if bad {
                eprintln!("[ERROR] Failed to apply netplan configuration");
                for l in stderr.lines().filter(|l| l.starts_with("Error") || l.contains("Conflicting")) {
                    eprintln!("[ERROR]     {}", l);
                }
                false
            } else {
                true
            }
        }
        Err(_) => {
            eprintln!("[ERROR] Could not run netplan");
            false
        }
    };

    // B1:apply 失败 → 恢复备份
    if !apply_ok {
        let _ = fs::copy(&bak, &file_path);
        eprintln!("[ERROR] Restored {} from backup", file_path);
        let _ = Command::new("netplan").arg("apply").output();
        std::process::exit(1);
    }
    println!("[INFO] Netplan configuration applied successfully");
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
/// 1. 直接数字 → 返回 2. allocated 已有该名 → 返回 3. 自动分配空闲 id(从 100 起)并写入 allocated
/// 返回 (id, 是否新分配)
fn resolve_table_id(t: &str, allocated: &mut std::collections::HashMap<String, u32>) -> (u32, bool) {
    if let Ok(n) = t.parse::<u32>() {
        return (n, false);
    }
    if let Some(&n) = allocated.get(t) {
        return (n, false);
    }
    let mut alloc = 100u32;
    while allocated.values().any(|&v| v == alloc) {
        alloc += 1;
    }
    allocated.insert(t.to_string(), alloc);
    (alloc, true)
}

/// 把 allocated 中比 initial 多出的条目追加写回 /etc/iproute2/rt_tables(去重)
fn writeback_rt_tables(allocated: &std::collections::HashMap<String, u32>, initial: &std::collections::HashMap<String, u32>) {
    let existing = {
        let mut base = initial.clone();
        if let Ok(content) = fs::read_to_string("/etc/iproute2/rt_tables") {
            for line in content.lines() {
                let line = line.trim();
                if line.is_empty() || line.starts_with('#') { continue; }
                let parts: Vec<&str> = line.split_whitespace().collect();
                if parts.len() >= 2 {
                    if let Ok(id) = parts[0].parse::<u32>() {
                        base.insert(parts[1].to_string(), id);
                    }
                }
            }
        }
        base
    };
    let mut to_write: Vec<(u32, String)> = allocated.iter()
        .filter(|(name, _)| !existing.contains_key(*name))
        .map(|(name, &id)| (id, name.clone()))
        .collect();
    to_write.sort_by_key(|(id, _)| *id);
    if to_write.is_empty() { return; }
    if let Ok(mut f) = fs::OpenOptions::new().append(true).open("/etc/iproute2/rt_tables") {
        for (id, name) in &to_write {
            let _ = writeln!(f, "{} {}", id, name);
        }
    }
}

// ============ nmcli 后端 ============

fn nmcli_render(cfg: &Config, allocated: &mut std::collections::HashMap<String, u32>) -> Vec<String> {
    let con_name = format!("static-{}", &cfg.net_device);
    let mut args: Vec<String> = vec![
        "con".into(), "add".into(), "type".into(), "ethernet".into(),
        "ifname".into(), cfg.net_device.clone().into(),
        "con-name".into(), con_name.clone().into(),
        "connection.autoconnect-priority".into(), "10".into(),
    ];

    if let Some(v4f) = &cfg.v4 {
        if v4f.is_dhcp {
            args.push("ipv4.method".into());
            args.push("auto".into());
        } else if !v4f.addrs.is_empty() {
            let addrs: Vec<String> = v4f.addrs.iter().map(|(a, p)| format!("{}/{}", a, p)).collect();
            args.push("ipv4.addresses".into());
            args.push(addrs.join(","));
            args.push("ipv4.method".into());
            args.push("manual".into());
            if let Some(gw) = &v4f.gateway {
                if !gw.is_empty() {
                    args.push("ipv4.gateway".into());
                    args.push(gw.clone());
                }
            }
            if let Some(dns) = &v4f.dns {
                if !dns.is_empty() {
                    args.push("ipv4.dns".into());
                    args.push(dns.clone());
                }
            }
        }
    }
    if let Some(v6f) = &cfg.v6 {
        if v6f.is_dhcp {
            args.push("ipv6.method".into());
            args.push("auto".into());
        } else if !v6f.addrs.is_empty() {
            let addrs: Vec<String> = v6f.addrs.iter().map(|(a, p)| format!("{}/{}", a, p)).collect();
            args.push("ipv6.addresses".into());
            args.push(addrs.join(","));
            args.push("ipv6.method".into());
            args.push("manual".into());
            if let Some(gw) = &v6f.gateway {
                if !gw.is_empty() {
                    args.push("ipv6.gateway".into());
                    args.push(gw.clone());
                }
            }
            if let Some(dns) = &v6f.dns {
                if !dns.is_empty() {
                    args.push("ipv6.dns".into());
                    args.push(dns.clone());
                }
            }
        }
    }
    // A4:路由 table=表名 → 数字 id
    if !cfg.routes.is_empty() {
        let entries: Vec<String> = cfg.routes.iter().map(|r| {
            let mut e = format!("{}/{}", r.to, r.to_prefix);
            if let Some(via) = &r.via {
                e.push_str(&format!(" {}", via));
            }
            if let Some(t) = &r.table {
                let (tid, _) = resolve_table_id(t, allocated);
                e.push_str(&format!(" table={}", tid));
            }
            e
        }).collect();
        args.push("ipv4.routes".into());
        args.push(entries.join(","));
    }
    // A1+A3:routing-rules,表名→id,from+to 单条
    if !cfg.policies.is_empty() {
        let mut rules: Vec<String> = Vec::new();
        let mut prio = 32760u32;
        for p in &cfg.policies {
            let t = p.table.as_deref().unwrap_or("");
            if t.is_empty() { continue; }
            let tid = match t.parse::<u32>() {
                Ok(n) => n,
                Err(_) => {
                    let (id, alloced) = resolve_table_id(t, allocated);
                    if alloced {
                        eprintln!("[INFO] nmcli: auto-assigned table id {} for name '{}'", id, t);
                    } else {
                        eprintln!("[INFO] nmcli: resolved table name '{}' → id {}", t, id);
                    }
                    id
                }
            };
            let mut rule = format!("priority {}", prio);
            if let Some((n, px)) = &p.from {
                rule.push_str(&format!(" from {}/{}", n, px));
            }
            if let Some((n, px)) = &p.to {
                rule.push_str(&format!(" to {}/{}", n, px));
            }
            rule.push_str(&format!(" table {}", tid));
            rules.push(rule);
            if prio > 100 { prio -= 1; }
        }
        if !rules.is_empty() {
            args.push("ipv4.routing-rules".into());
            args.push(rules.join(","));
        }
    }
    args
}

fn configure_with_nmcli(cfg: &Config) {
    let con_name = format!("static-{}", &cfg.net_device);
    let _ = Command::new("nmcli").args(["con", "delete", &con_name]).output();

    let initial = load_rt_tables();
    let mut allocated = initial.clone();
    if let Some(v4f) = &cfg.v4 {
        if v4f.is_dhcp || (!v4f.addrs.is_empty() && v4f.gateway.as_deref().map(|g| !g.is_empty()).unwrap_or(false)) {
            warn_extra_routes(&cfg.net_device);
        }
    }
    let add_args = nmcli_render(cfg, &mut allocated);
    writeback_rt_tables(&allocated, &initial);

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

fn networkd_render(cfg: &Config) -> (String, String) {
    let file_path = format!("/etc/systemd/network/10-{}.network", cfg.net_device);
    let mut s = String::new();
    s.push_str("[Match]\n");
    s.push_str(&format!("Name={}\n\n", cfg.net_device));
    s.push_str("[Network]\n");
    if let Some(v4f) = &cfg.v4 {
        if v4f.is_dhcp {
            s.push_str("DHCP=ipv4\n");
        } else {
            for (a, p) in &v4f.addrs {
                s.push_str(&format!("Address={}/{}\n", a, p));
            }
            if let Some(gw) = &v4f.gateway {
                if !gw.is_empty() {
                    s.push_str(&format!("Gateway={}\n", gw));
                }
            }
        }
    }
    if let Some(v6f) = &cfg.v6 {
        if v6f.is_dhcp {
            s.push_str("DHCP=ipv6\n");
        } else {
            for (a, p) in &v6f.addrs {
                s.push_str(&format!("Address={}/{}\n", a, p));
            }
            if let Some(gw) = &v6f.gateway {
                if !gw.is_empty() {
                    s.push_str(&format!("Gateway={}\n", gw));
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
        s.push_str(&format!("DNS={}\n", dns_list.join(" ")));
    }
    for r in &cfg.routes {
        s.push_str("\n[Route]\n");
        s.push_str(&format!("Destination={}/{}\n", r.to, r.to_prefix));
        if let Some(via) = &r.via {
            s.push_str(&format!("Gateway={}\n", via));
        }
        if let Some(t) = &r.table {
            s.push_str(&format!("Table={}\n", t));
        }
    }
    for p in &cfg.policies {
        if let Some(t) = &p.table {
            // A3:from+to 同存 → 单个 [RoutingPolicyRule] 段
            s.push_str("\n[RoutingPolicyRule]\n");
            if let Some((n, px)) = &p.from {
                s.push_str(&format!("From={}/{}\n", n, px));
            }
            if let Some((n, px)) = &p.to {
                s.push_str(&format!("To={}/{}\n", n, px));
            }
            s.push_str(&format!("Table={}\n", t));
        }
    }
    (file_path, s)
}

fn configure_with_networkd(cfg: &Config) {
    // C5:与 netplan/nmcli/ip 对齐,多默认网关时告警
    if let Some(v4f) = &cfg.v4 {
        if !v4f.is_dhcp {
            if let Some(gw) = &v4f.gateway {
                if !gw.is_empty() {
                    warn_extra_routes(&cfg.net_device);
                }
            }
        }
    }

    let (file_path, content) = networkd_render(cfg);
    let mut file = fs::File::create(&file_path).expect("[ERROR] Failed to create networkd config file");
    file.write_all(content.as_bytes()).unwrap();

    println!("[INFO] Created systemd-networkd config at {}", file_path);
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

/// 返回当前 main 表默认路由所在设备(解析 `ip route show default` 的 `dev X`)
fn default_route_dev() -> Option<String> {
    let out = Command::new("ip").args(["route", "show", "default"]).output().ok()?;
    let s = String::from_utf8_lossy(&out.stdout);
    for line in s.lines() {
        if line.starts_with("default ") {
            let mut dev = None;
            let mut iter = line.split_whitespace();
            while let Some(tok) = iter.next() {
                if tok == "dev" {
                    dev = iter.next().map(|x| x.to_string());
                    break;
                }
            }
            if dev.is_some() {
                return dev;
            }
        }
    }
    None
}

/// 生成 ip 兜底要执行的命令参数序列(纯函数,不执行)
fn ip_render(cfg: &Config) -> Vec<Vec<String>> {
    let mut cmds: Vec<Vec<String>> = Vec::new();
    cmds.push(vec!["addr".into(), "flush".into(), "dev".into(), cfg.net_device.clone()]);
    cmds.push(vec!["link".into(), "set".into(), "dev".into(), cfg.net_device.clone(), "up".into()]);
    if let Some(v4f) = &cfg.v4 {
        for (a, p) in &v4f.addrs {
            cmds.push(vec!["addr".into(), "add".into(), format!("{}/{}", a, p), "dev".into(), cfg.net_device.clone()]);
        }
        if let Some(gw) = &v4f.gateway {
            if !gw.is_empty() {
                cmds.push(vec!["route".into(), "add".into(), "default".into(), "via".into(), gw.clone(), "dev".into(), cfg.net_device.clone()]);
            }
        }
    }
    if let Some(v6f) = &cfg.v6 {
        for (a, p) in &v6f.addrs {
            cmds.push(vec!["addr".into(), "add".into(), format!("{}/{}", a, p), "dev".into(), cfg.net_device.clone()]);
        }
    }
    for r in &cfg.routes {
        let mut c: Vec<String> = vec!["route".into(), "add".into(), format!("{}/{}", r.to, r.to_prefix)];
        if let Some(via) = &r.via {
            c.push("via".into());
            c.push(via.clone());
        }
        c.push("dev".into());
        c.push(cfg.net_device.clone());
        if let Some(t) = &r.table {
            c.push("table".into());
            c.push(t.clone());
        }
        cmds.push(c);
    }
    for p in &cfg.policies {
        if let Some(t) = &p.table {
            // A3:from+to 同存 → 单条 rule
            let mut c: Vec<String> = vec!["rule".into(), "add".into()];
            if let Some((n, px)) = &p.from {
                c.push("from".into());
                c.push(format!("{}/{}", n, px));
            }
            if let Some((n, px)) = &p.to {
                c.push("to".into());
                c.push(format!("{}/{}", n, px));
            }
            c.push("table".into());
            c.push(t.clone());
            cmds.push(c);
        }
    }
    cmds.push(vec!["link".into(), "set".into(), "dev".into(), cfg.net_device.clone(), "up".into()]);
    cmds
}

fn configure_with_ip(cfg: &Config) {
    let any_dhcp = cfg.v4.as_ref().map(|f| f.is_dhcp).unwrap_or(false)
        || cfg.v6.as_ref().map(|f| f.is_dhcp).unwrap_or(false);
    if any_dhcp {
        eprintln!("[ERROR] DHCP is not supported when using manual IP configuration");
        return;
    }

    // C6:保护当前默认路由所在设备(通常是管理口),避免 flush 断 SSH
    if !cfg.force {
        if let Some(dev) = default_route_dev() {
            if dev == cfg.net_device {
                eprintln!(
                    "[ERROR] refusing to flush {}: it carries the default route (likely management iface); use --force to override",
                    cfg.net_device
                );
                std::process::exit(1);
            }
        }
    }

    // C5:与 netplan/networkd/nmcli 对齐,多默认网关时告警
    if let Some(v4f) = &cfg.v4 {
        if !v4f.is_dhcp {
            if let Some(gw) = &v4f.gateway {
                if !gw.is_empty() {
                    warn_extra_routes(&cfg.net_device);
                }
            }
        }
    }

    let run = |args: &[String]| -> bool {
        let refs: Vec<&str> = args.iter().map(|s| s.as_str()).collect();
        let out = Command::new("ip").args(&refs).output();
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

    let cmds = ip_render(cfg);
    // 统计地址成功数(地址命令在 flush/link 之后、最后 link 之前)
    let mut addr_ok = 0usize;
    let mut addr_total = 0usize;
    for c in &cmds {
        if c.len() >= 2 && c[0] == "addr" && c[1] == "add" {
            addr_total += 1;
            if run(c) {
                addr_ok += 1;
            }
        } else if c.len() >= 3 && c[0] == "route" && c[1] == "add" && c[2] == "default" {
            if !run(c) {
                eprintln!("[WARNING] default route not added (another default route may exist in table main; use policy routing for multi-gateway)");
            }
        } else {
            run(c);
        }
    }
    if addr_total > 0 && addr_ok == 0 {
        eprintln!("[ERROR] Failed to add any of the {} address(es) to {}", addr_total, cfg.net_device);
    }
    println!("[INFO] Manual IP configuration applied (addresses: {}/{})", addr_ok, addr_total);
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;

    fn cfg_ip(routes: Vec<Route>, policies: Vec<Policy>, force: bool) -> Config {
        Config {
            net_device: "eth1".into(),
            family1_is_v6: false,
            v4: Some(Family {
                addrs: vec![("1.1.1.1".into(), 24)],
                gateway: Some("1.1.1.254".into()),
                dns: None,
                is_dhcp: false,
            }),
            v6: None,
            routes,
            policies,
            dry_run: false,
            force,
        }
    }

    #[test]
    fn ip_render_policy_from_to_single_rule() {
        let p = Policy {
            from: Some(("10.0.0.0".into(), 24)),
            to: Some(("192.168.3.0".into(), 24)),
            table: Some("100".into()),
        };
        let cfg = cfg_ip(vec![], vec![p], false);
        let cmds = ip_render(&cfg);
        // 应只有一条 rule,同时带 from + to
        let rules: Vec<&Vec<String>> = cmds.iter().filter(|c| c.first().map(|s| s == "rule").unwrap_or(false)).collect();
        assert_eq!(rules.len(), 1, "from+to 应生成单条 rule,实际: {:?}", rules);
        let joined = rules[0].join(" ");
        assert!(joined.contains("from 10.0.0.0/24"), "缺 from: {}", joined);
        assert!(joined.contains("to 192.168.3.0/24"), "缺 to: {}", joined);
        assert!(joined.contains("table 100"), "缺 table: {}", joined);
    }

    #[test]
    fn ip_render_flush_and_addr() {
        let cfg = cfg_ip(vec![], vec![], false);
        let cmds = ip_render(&cfg);
        let joined: Vec<String> = cmds.iter().map(|c| c.join(" ")).collect();
        assert!(joined.iter().any(|s| s == "addr flush dev eth1"), "缺 flush: {:?}", joined);
        assert!(joined.iter().any(|s| s == "addr add 1.1.1.1/24 dev eth1"), "缺 addr add: {:?}", joined);
        assert!(joined.iter().any(|s| s == "route add default via 1.1.1.254 dev eth1"), "缺默认路由: {:?}", joined);
    }

    #[test]
    fn networkd_render_policy_from_to_single_section() {
        let p = Policy {
            from: Some(("10.0.0.0".into(), 24)),
            to: Some(("192.168.3.0".into(), 24)),
            table: Some("100".into()),
        };
        let cfg = cfg_ip(vec![], vec![p], false);
        let (path, content) = networkd_render(&cfg);
        assert!(path.ends_with("10-eth1.network"), "路径错: {}", path);
        // 单个 [RoutingPolicyRule] 段同时含 From= 和 To=
        let sections: Vec<&str> = content.split("[RoutingPolicyRule]").collect();
        assert_eq!(sections.len(), 2, "from+to 应单个段,实际:\n{}", content);
        let rule = sections[1];
        assert!(rule.contains("From=10.0.0.0/24"), "缺 From: {}", rule);
        assert!(rule.contains("To=192.168.3.0/24"), "缺 To: {}", rule);
        assert!(rule.contains("Table=100"), "缺 Table: {}", rule);
    }

    #[test]
    fn networkd_render_multi_addr_and_route() {
        let cfg = cfg_ip(
            vec![Route { to: "192.168.2.0".into(), to_prefix: 24, via: Some("1.1.1.254".into()), table: Some("100".into()) }],
            vec![],
            false,
        );
        let (_path, content) = networkd_render(&cfg);
        assert!(content.contains("Address=1.1.1.1/24"), "缺地址: {}", content);
        assert!(content.contains("Gateway=1.1.1.254"), "缺网关: {}", content);
        assert!(content.contains("[Route]"), "缺 Route 段: {}", content);
        assert!(content.contains("Destination=192.168.2.0/24"), "缺 Destination: {}", content);
    }

    #[test]
    fn nmcli_render_two_unknown_tables_distinct_ids() {
        // A1:两个未知表名应分到不同 id
        let p1 = Policy { from: Some(("10.0.0.0".into(), 24)), to: None, table: Some("mystery_a".into()) };
        let p2 = Policy { from: Some(("10.1.0.0".into(), 24)), to: None, table: Some("mystery_b".into()) };
        let cfg = cfg_ip(vec![], vec![p1, p2], false);
        let mut allocated = HashMap::new(); // 空 rt_tables
        let args = nmcli_render(&cfg, &mut allocated);
        // nmcli_render joins rules with comma in a single arg; split to inspect
        let rules_joined = args.iter().find(|a| a.starts_with("priority ")).unwrap();
        let rules: Vec<&str> = rules_joined.split(',').collect();
        assert_eq!(rules.len(), 2, "应有 2 条 rule: {:?}", rules_joined);
        let id_a: u32 = rules[0].rsplit("table ").next().unwrap().parse().unwrap();
        let id_b: u32 = rules[1].rsplit("table ").next().unwrap().parse().unwrap();
        assert_ne!(id_a, id_b, "两个未知表名不应分到同一 id: {} vs {}", id_a, id_b);
        // allocated 应记录两个名字
        assert_eq!(allocated.get("mystery_a"), Some(&id_a));
        assert_eq!(allocated.get("mystery_b"), Some(&id_b));
    }

    #[test]
    fn nmcli_render_route_table_name_to_id() {
        // A4:路由 table=表名 应解析为数字
        let r = Route { to: "192.168.2.0".into(), to_prefix: 24, via: Some("1.1.1.254".into()), table: Some("lan_table".into()) };
        let cfg = cfg_ip(vec![r], vec![], false);
        let mut allocated = HashMap::from([("lan_table".to_string(), 101u32)]);
        let args = nmcli_render(&cfg, &mut allocated);
        let routes_arg = args.iter().find(|a| a.contains("table=")).unwrap();
        assert!(routes_arg.contains("table=101"), "路由表名应解析为数字 101: {}", routes_arg);
        assert!(!routes_arg.contains("table=lan_table"), "不应保留表名: {}", routes_arg);
    }

    #[test]
    fn nmcli_render_policy_from_to_single_rule() {
        // A3:from+to 单条 rule
        let p = Policy { from: Some(("10.0.0.0".into(), 24)), to: Some(("192.168.3.0".into(), 24)), table: Some("100".into()) };
        let cfg = cfg_ip(vec![], vec![p], false);
        let mut allocated = HashMap::new();
        let args = nmcli_render(&cfg, &mut allocated);
        // nmcli_render joins rules with comma in a single arg
        let rules_joined = args.iter().find(|a| a.starts_with("priority ")).unwrap();
        let rules: Vec<&str> = rules_joined.split(',').collect();
        assert_eq!(rules.len(), 1, "from+to 应单条 rule: {:?}", rules_joined);
        let joined = rules[0];
        assert!(joined.contains("from 10.0.0.0/24") && joined.contains("to 192.168.3.0/24"), "缺 from/to: {}", joined);
    }

    #[test]
    fn netplan_render_policy_from_to_single_item() {
        // A3:from+to 单个 routing-policy 项
        let p = Policy { from: Some(("10.0.0.0".into(), 24)), to: Some(("192.168.3.0".into(), 24)), table: Some("100".into()) };
        let cfg = cfg_ip(vec![], vec![p], false);
        let existing = "network:\n  version: 2\n  ethernets:\n    eth1:\n      mtu: 9000\n";
        let out = netplan_render(&cfg, existing, "/etc/netplan/01-netcfg.yaml");
        assert!(out.is_ok(), "render 失败: {:?}", out);
        let yaml = out.unwrap();
        // 应保留 mtu(B3)
        assert!(yaml.contains("mtu: 9000"), "B3:应保留原 mtu:\n{}", yaml);
        // routing-policy 应只有一项含 from+to
        let pol_count = yaml.matches("from: 10.0.0.0/24").count();
        assert_eq!(pol_count, 1, "A3:from 应只出现一次:\n{}", yaml);
        assert!(yaml.contains("to: 192.168.3.0/24"), "A3:缺 to:\n{}", yaml);
    }

    #[test]
    fn netplan_render_preserves_unmanaged_fields() {
        // B3:保留 match/set-name/receive-checksum-offload
        let cfg = cfg_ip(vec![], vec![], false);
        let existing = "network:\n  version: 2\n  ethernets:\n    eth1:\n      mtu: 1500\n      match:\n        macaddress: 00:11:22:33:44:55\n      set-name: eth1\n      receive-checksum-offload: false\n";
        let yaml = netplan_render(&cfg, existing, "/etc/netplan/01-netcfg.yaml").unwrap();
        assert!(yaml.contains("macaddress: 00:11:22:33:44:55"), "B3:丢 match:\n{}", yaml);
        assert!(yaml.contains("set-name: eth1"), "B3:丢 set-name:\n{}", yaml);
        assert!(yaml.contains("receive-checksum-offload: false"), "B3:丢 checksum:\n{}", yaml);
    }

    #[test]
    fn netplan_render_non_mapping_top_errors() {
        // C8:顶层非 mapping → Err 而非 panic
        let cfg = cfg_ip(vec![], vec![], false);
        let out = netplan_render(&cfg, "not a mapping\n", "/etc/netplan/01-netcfg.yaml");
        assert!(out.is_err(), "C8:非 mapping 应 Err");
    }
}
