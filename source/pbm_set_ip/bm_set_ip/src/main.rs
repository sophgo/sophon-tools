use lexopt;
use serde_yaml;
use serde_yaml::{Mapping, Value};
use std::collections::HashMap;
use std::env;
use std::fs;
use std::io;
use std::io::Write;
use std::path::Path;
use std::process::exit;
use std::process::Command;
use std::process::Stdio;

// ============ 数据结构 ============

/// 一个地址族(v4 或 v6),可含多个地址
struct Family {
    /// (地址, 前缀)
    addrs: Vec<(String, u8)>,
    gateway: Option<String>,
    /// 逗号分隔的 DNS 列表 → 数组(空 vec = 无 DNS)
    dns: Vec<String>,
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
        if net_device.is_empty() {
            return Err("net_device must not be empty".into());
        }
        if !is_valid_net_device(&net_device) {
            return Err(format!(
                "invalid net_device '{}': interface name must be 1-16 chars of letters/digits/._:- (no '/' or whitespace)",
                net_device
            )
            .into());
        }
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
        let dnsv = parse_dns_opt(&dns, true)?;
        let prefix = match &nm {
            Some(m) => parse_prefix(m, 128)?,
            None => 128,
        };
        let v6f = Family {
            addrs: vec![(addr1, prefix)],
            gateway: gw,
            dns: dnsv,
            is_dhcp: false,
        };
        (None, Some(v6f))
    } else {
        let is_dhcp4 = is_dhcp_token(&addr1);
        let dnsv = parse_dns_opt(&dns, false)?;
        let v4f = if is_dhcp4 {
            validate_opt_gateway(&gw, false)?;
            Family { addrs: vec![], gateway: gw, dns: dnsv, is_dhcp: true }
        } else {
            validate_ip(&addr1, false)?;
            validate_opt_gateway(&gw, false)?;
            let prefix = match &nm {
                Some(m) => mask_to_prefix_checked(m, 32)?,
                None => 32,
            };
            Family { addrs: vec![(addr1, prefix)], gateway: gw, dns: dnsv, is_dhcp: false }
        };
        let v6f = if ipv6.is_some() {
            let is_dhcp6 = ipv6.as_deref().map(is_dhcp_token).unwrap_or(false);
            if is_dhcp6 {
                validate_opt_gateway(&ipv6_gateway, true)?;
                let dnsv6 = parse_dns_opt(&ipv6_dns, true)?;
                Some(Family { addrs: vec![], gateway: ipv6_gateway, dns: dnsv6, is_dhcp: true })
            } else {
                let a = ipv6.as_deref().unwrap();
                validate_ip(a, true)?;
                validate_opt_gateway(&ipv6_gateway, true)?;
                let dnsv6 = parse_dns_opt(&ipv6_dns, true)?;
                let prefix = match &ipv6_prefix {
                    Some(m) => parse_prefix(m, 128)?,
                    None => 128,
                };
                Some(Family {
                    addrs: vec![(a.to_string(), prefix)],
                    gateway: ipv6_gateway,
                    dns: dnsv6,
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
        let dnsv = parse_dns_opt(&dns, true)?;
        let p = match &prefix {
            Some(m) => parse_prefix(m, 128)?,
            None => 128,
        };
        v6 = Some(Family { addrs: vec![(addr1, p)], gateway: gw, dns: dnsv, is_dhcp: false });
    } else if family1_is_dhcp {
        // dhcp 单 token。若紧跟 3 个空槽('' '' '')则消费之(对齐 4 元组),
        // 否则不动(向后兼容 dhcp 直接接路由/策略/family2)。
        if rest.get(i).map(|s| s.is_empty()).unwrap_or(false)
            && rest.get(i + 1).map(|s| s.is_empty()).unwrap_or(false)
            && rest.get(i + 2).map(|s| s.is_empty()).unwrap_or(false)
        {
            i += 3;
        }
        v4 = Some(Family { addrs: vec![], gateway: None, dns: vec![], is_dhcp: true });
    } else {
        // v4 static family1:4 元组(addr1 已消费,读 mask/gw/dns)
        validate_ip(&addr1, false)?;
        let (mask, gw, dns) = read_3slots(rest, &mut i);
        validate_opt_gateway(&gw, false)?;
        let dnsv = parse_dns_opt(&dns, false)?;
        let p = match &mask {
            Some(m) => mask_to_prefix_checked(m, 32)?,
            None => 32,
        };
        v4 = Some(Family { addrs: vec![(addr1, p)], gateway: gw, dns: dnsv, is_dhcp: false });
    }

    let mut routes: Vec<Route> = Vec::new();
    let mut policies: Vec<Policy> = Vec::new();

    loop {
        let pos1 = match rest.get(i) {
            Some(s) if !s.is_empty() => s.clone(),
            Some(_) => {
                return Err(format!(
                    "unexpected empty token at position {}: each 4-tuple group must start with a non-empty address; remove stray '' tokens",
                    i
                )
                .into());
            }
            None => break,
        };
        // family2 门:family1 为 v4 且 pos1 为 v6/dhcp
        if !family1_is_v6 && jumps_to_family2(&pos1) {
            i += 1; // 消费 pos1(family2 addr/dhcp)
            if is_dhcp_token(&pos1) {
                v6 = Some(Family { addrs: vec![], gateway: None, dns: vec![], is_dhcp: true });
            } else {
                validate_ip(&pos1, true)?;
                let (prefix, gw, dns) = read_3slots(rest, &mut i);
                validate_opt_gateway(&gw, true)?;
                let dnsv = parse_dns_opt(&dns, true)?;
                let p = match &prefix {
                    Some(m) => parse_prefix(m, 128)?,
                    None => 128,
                };
                v6 = Some(Family { addrs: vec![(pos1, p)], gateway: gw, dns: dnsv, is_dhcp: false });
            }
            // family2 之后不允许再有 token(组顺序:[family2] 必须是最后一个)
            if i < rest.len() {
                return Err(format!(
                    "unexpected tokens after IPv6 family: {} trailing token(s) starting at '{}' (group order is [family1] [extra-addr]* [route]* [policy]* [family2])",
                    rest.len() - i,
                    rest[i]
                )
                .into());
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
/// Linux 接口名约束:1-16 字符,允许字母/数字/./_/-(无 '/'、空白)。
fn is_valid_net_device(s: &str) -> bool {
    !s.is_empty()
        && s.len() <= 16
        && s.chars()
            .all(|c| c.is_ascii_alphanumeric() || c == '.' || c == '_' || c == '-' || c == ':')
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

/// 解析逗号分隔的 DNS 列表 → 数组:逐项 trim 并校验,重复项去重。
/// `is_v6` 指定族:与 family 族不一致的项(如 v4 family 里的 IPv6 DNS)
/// 直接报错——各后端(nmcli ipv4.dns/ipv6.dns 等)按族隔离,混族会在运行时失败。
/// 如 "8.8.8.8, 114.114.114.114" → ["8.8.8.8", "114.114.114.114"]。
fn parse_dns(s: &str, is_v6: bool) -> Result<Vec<String>, String> {
    let mut out: Vec<String> = Vec::new();
    for item in s.split(',') {
        let t = item.trim();
        if t.is_empty() {
            return Err(format!(
                "invalid DNS server list '{}': empty entry (stray ',' or blank item)",
                s
            ));
        }
        let ok = if is_v6 { is_valid_ipv6(t) } else { is_valid_ipv4(t) };
        if !ok {
            return Err(format!(
                "invalid DNS server '{}': expected {} address (DNS list must be single-family, v4 and v6 cannot mix)",
                t,
                if is_v6 { "IPv6" } else { "IPv4" }
            ));
        }
        if !out.iter().any(|x| x == t) {
            out.push(t.to_string());
        }
    }
    Ok(out)
}

/// 可选的 DNS 槽(None/空 → 空数组),调用方先过此转换再存 Family
fn parse_dns_opt(opt: &Option<String>, is_v6: bool) -> Result<Vec<String>, String> {
    match opt {
        Some(s) if !s.is_empty() => parse_dns(s, is_v6),
        _ => Ok(Vec::new()),
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
                println!("{}.dns={}", label, f.dns.join(","));
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
// ============ 外部命令 / 文件系统访问（可注入，便于 stateful fake 测试）============

/// 一条外部命令的执行结果。ok=false 表示命令不可用、非零退出或等待失败。
#[derive(Debug, Clone, Default)]
struct Out {
    ok: bool,
    stdout: String,
    stderr: String,
}

impl Out {
    #[cfg(test)] // 仅测试 fake 需要构造成功输出
    fn ok_with(stdout: impl Into<String>) -> Self {
        Out {
            ok: true,
            stdout: stdout.into(),
            stderr: String::new(),
        }
    }

    fn fail_with(stderr: impl Into<String>) -> Self {
        Out {
            ok: false,
            stdout: String::new(),
            stderr: stderr.into(),
        }
    }

    /// 失败详情（优先 stderr，其次 stdout），拼进错误消息
    fn detail(&self) -> String {
        let e = self.stderr.trim();
        let o = self.stdout.trim();
        let s = if !e.is_empty() { e } else { o };
        if s.is_empty() {
            String::new()
        } else {
            format!(": {}", s)
        }
    }
}

/// 后端依赖的外部能力。生产实现直接调真实命令/文件；测试注入 stateful fake，
/// 使 NM / ip / DNS / 快照逻辑能在不触碰宿主网络的前提下被断言。
trait Env {
    fn which(&mut self, program: &str) -> bool;
    fn run(&mut self, program: &str, args: &[&str]) -> Out;
    /// 带 stdin 的执行：一次性写入全部输入并等待退出（不留下未回收子进程）
    fn run_stdin(&mut self, program: &str, args: &[&str], input: &str) -> Out;
    fn read(&mut self, path: &str) -> io::Result<String>;
    fn exists(&mut self, path: &str) -> bool;
    fn write(&mut self, path: &str, content: &str) -> io::Result<()>;
    fn remove(&mut self, path: &str) -> io::Result<()>;
    fn list_files(&mut self, dir: &str) -> Vec<String>;
    /// 面向用户的提示。成功文案只允许出现在成功路径上。
    fn say(&mut self, msg: &str);
}

/// 生产实现：真实命令 + 真实文件系统
struct OsEnv;

impl OsEnv {
    fn new() -> Self {
        OsEnv
    }
}

impl Env for OsEnv {
    fn which(&mut self, program: &str) -> bool {
        is_command_exists(program)
    }

    fn run(&mut self, program: &str, args: &[&str]) -> Out {
        match Command::new(program).args(args).output() {
            Ok(o) => Out {
                ok: o.status.success(),
                stdout: String::from_utf8_lossy(&o.stdout).into_owned(),
                stderr: String::from_utf8_lossy(&o.stderr).into_owned(),
            },
            Err(e) => Out::fail_with(format!("could not execute {}: {}", program, e)),
        }
    }

    fn run_stdin(&mut self, program: &str, args: &[&str], input: &str) -> Out {
        let mut child = match Command::new(program)
            .args(args)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
        {
            Ok(c) => c,
            Err(e) => return Out::fail_with(format!("could not execute {}: {}", program, e)),
        };
        // 写完立刻关闭 stdin（drop），子进程才能读到 EOF
        if let Some(mut si) = child.stdin.take() {
            if let Err(e) = si.write_all(input.as_bytes()) {
                let _ = child.wait();
                return Out::fail_with(format!("failed to write stdin of {}: {}", program, e));
            }
        }
        match child.wait_with_output() {
            Ok(o) => Out {
                ok: o.status.success(),
                stdout: String::from_utf8_lossy(&o.stdout).into_owned(),
                stderr: String::from_utf8_lossy(&o.stderr).into_owned(),
            },
            Err(e) => Out::fail_with(format!("failed to wait for {}: {}", program, e)),
        }
    }

    fn read(&mut self, path: &str) -> io::Result<String> {
        fs::read_to_string(path)
    }

    fn exists(&mut self, path: &str) -> bool {
        Path::new(path).exists()
    }

    fn write(&mut self, path: &str, content: &str) -> io::Result<()> {
        fs::write(path, content)
    }

    fn remove(&mut self, path: &str) -> io::Result<()> {
        match fs::remove_file(path) {
            Ok(()) => Ok(()),
            // 目标本来就不存在（例如新建文件写入前就失败）：视为已达成“撤销新文件”
            Err(e) if e.kind() == io::ErrorKind::NotFound => Ok(()),
            Err(e) => Err(e),
        }
    }

    fn list_files(&mut self, dir: &str) -> Vec<String> {
        let mut out = Vec::new();
        if let Ok(entries) = fs::read_dir(dir) {
            for e in entries.flatten() {
                if let Some(name) = e.file_name().to_str() {
                    out.push(name.to_string());
                }
            }
        }
        out
    }

    fn say(&mut self, msg: &str) {
        println!("{}", msg);
    }
}

/// 通用辅助 ================================================================

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

/// 执行命令并在失败时返回带上下文的错误（关键命令一律走这里，禁止吞掉失败）
fn run_checked(env: &mut dyn Env, program: &str, args: &[&str]) -> Result<(), String> {
    let out = env.run(program, args);
    if out.ok {
        Ok(())
    } else {
        Err(format!(
            "`{} {}` failed{}",
            program,
            args.join(" "),
            out.detail()
        ))
    }
}

fn extra_default_routes(env: &mut dyn Env, current_dev: &str) -> Vec<String> {
    let mut others = Vec::new();
    let out = env.run("ip", &["route", "show", "default"]);
    if out.ok {
        for line in out.stdout.lines() {
            if line.starts_with("default ") && !line.contains(&format!("dev {}", current_dev)) {
                others.push(line.to_string());
            }
        }
    }
    others
}

/// 多默认网关告警（纯提示，不影响退出码：配置本身仍会完整写入并生效）。
/// 条件与 nmcli 后端历史行为对齐：v4 为 dhcp，或 v4 静态且显式给了网关。
fn warn_extra_routes(env: &mut dyn Env, cfg: &Config) {
    let needs = match &cfg.v4 {
        Some(f) if f.is_dhcp => true,
        Some(f) => f.gateway.as_deref().map(|g| !g.is_empty()).unwrap_or(false),
        None => false,
    };
    if !needs {
        return;
    }
    let extra = extra_default_routes(env, &cfg.net_device);
    if !extra.is_empty() {
        env.say("[WARNING] system has extra default routes on other devices:");
        for r in &extra {
            env.say(&format!("[WARNING]     {}", r));
        }
    }
}

fn detect_net_manager(env: &mut dyn Env) -> NetManager {
    // B2:netplan 命令存在 且 /etc/netplan/ 下任一 *.yaml 存在
    if env.which("netplan")
        && env
            .list_files("/etc/netplan")
            .iter()
            .any(|f| f.ends_with(".yaml"))
    {
        return NetManager::Netplan;
    }
    if env.which("nmcli") {
        let out = env.run("systemctl", &["is-active", "NetworkManager"]);
        if out.ok && out.stdout.trim() == "active" {
            return NetManager::NetworkManager;
        }
    }
    let out = env.run("systemctl", &["is-active", "systemd-networkd"]);
    if out.ok && out.stdout.trim() == "active" {
        return NetManager::SystemdNetworkd;
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

// ============ 配置快照与回滚 ============

/// 写前快照：明确区分“原文件存在（内容已捕获）”与“原文件不存在”。
/// 回滚只使用本快照，绝不读取可能来自历史遗留的 `.bak`。
#[derive(Debug, Clone, PartialEq)]
enum Snapshot {
    Missing,
    Present(String),
}

fn snapshot(env: &mut dyn Env, path: &str) -> Result<Snapshot, String> {
    if !env.exists(path) {
        return Ok(Snapshot::Missing);
    }
    match env.read(path) {
        Ok(c) => Ok(Snapshot::Present(c)),
        // 读不到原文就无法回滚 → 拒绝修改，避免把已有配置写坏
        Err(e) => Err(format!(
            "cannot snapshot {} (refusing to modify): {}",
            path, e
        )),
    }
}

/// 按本次快照回滚：原文件存在则写回原文，原文件不存在则撤销本次新建的文件
fn restore_snapshot(env: &mut dyn Env, path: &str, snap: &Snapshot) -> Result<(), String> {
    match snap {
        Snapshot::Present(c) => match env.write(path, c) {
            Ok(()) => Ok(()),
            Err(e) => Err(format!("failed to restore {}: {}", path, e)),
        },
        Snapshot::Missing => match env.remove(path) {
            Ok(()) => Ok(()),
            Err(e) => Err(format!("failed to remove newly created {}: {}", path, e)),
        },
    }
}

/// 写出供人工恢复用的 `.bak`（内容取自本次快照）。写失败即拒绝修改。
/// 该文件只是运维便利，回滚绝不依赖它。
fn write_backup(env: &mut dyn Env, path: &str, snap: &Snapshot) -> Result<Option<String>, String> {
    match snap {
        Snapshot::Present(c) => {
            let bak = format!("{}.bm_set_ip.bak", path);
            match env.write(&bak, c) {
                Ok(()) => Ok(Some(bak)),
                Err(e) => Err(format!(
                    "cannot back up {} to {} (refusing to modify): {}",
                    path, bak, e
                )),
            }
        }
        // 原文件不存在时没有可备份的内容，也不能凭空产生 .bak
        Snapshot::Missing => Ok(None),
    }
}

// ============ netplan 后端 ============

fn select_netplan_file(env: &mut dyn Env) -> String {
    if let Ok(f) = std::env::var("BM_SET_IP_NETPLAN_FILE") {
        if !f.is_empty() {
            return f;
        }
    }
    let mut yamls: Vec<String> = env
        .list_files("/etc/netplan")
        .into_iter()
        .filter(|n| n.ends_with(".yaml"))
        .collect();
    yamls.sort();
    if let Some(last) = yamls.last() {
        format!("/etc/netplan/{}", last)
    } else {
        env.say("[WARNING] no /etc/netplan/*.yaml found, falling back to 01-netcfg.yaml");
        "/etc/netplan/01-netcfg.yaml".to_string()
    }
}

fn netplan_render(
    cfg: &Config,
    existing_yaml: &str,
    target_file: &str,
    rt: &HashMap<String, u32>,
) -> Result<String, String> {
    let _ = target_file;
    let mut doc: serde_yaml::Value =
        serde_yaml::from_str(existing_yaml).map_err(|e| format!("YAML parsing failed: {}", e))?;
    let network_map = doc
        .as_mapping_mut()
        .ok_or_else(|| "netplan yaml top-level is not a mapping".to_string())?;
    let ethernets_map = get_or_create_mapping(network_map, "network")?;
    let ethernets = get_or_create_mapping(ethernets_map, "ethernets")?;

    // B3:若设备已存在且为 mapping,在其上更新;否则新建
    let dev_key = Value::String(cfg.net_device.clone());
    let mut dev_cfg = match ethernets.get(&dev_key) {
        Some(Value::Mapping(m)) => m.clone(),
        _ => serde_yaml::Mapping::new(),
    };
    // 本工具管理的键(更新前移除,再按当前配置写入)
    for k in [
        "dhcp4",
        "dhcp6",
        "addresses",
        "routes",
        "routing-policy",
        "nameservers",
        "optional",
        "gateway4",
        "gateway6",
    ] {
        dev_cfg.remove(Value::String(k.into()));
    }
    // 表名 → 数字 id(netplan routes/routing-policy 的 table 只接受数字)
    let resolve_t = |t: &str| -> Result<String, String> {
        if t.parse::<u32>().is_ok() {
            return Ok(t.to_string());
        }
        match rt.get(t) {
            Some(&id) => Ok(id.to_string()),
            None => Err(format!(
                "table name '{}' not found in /etc/iproute2/rt_tables; netplan requires a numeric table (add '{} <id>' to rt_tables, or use a numeric table)",
                t, t
            )),
        }
    };

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
                    r.insert(
                        Value::String("to".into()),
                        Value::String("0.0.0.0/0".into()),
                    );
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
        m.insert(
            Value::String("to".into()),
            Value::String(format!("{}/{}", r.to, r.to_prefix)),
        );
        if let Some(via) = &r.via {
            m.insert(Value::String("via".into()), Value::String(via.clone()));
        }
        if let Some(t) = &r.table {
            m.insert(Value::String("table".into()), Value::String(resolve_t(t)?));
        }
        routes_seq.push(Value::Mapping(m));
    }
    if !addresses_seq.is_empty() {
        dev_cfg.insert(
            Value::String("addresses".into()),
            Value::Sequence(addresses_seq),
        );
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
                m.insert(
                    Value::String("from".into()),
                    Value::String(format!("{}/{}", n, px)),
                );
            }
            if let Some((n, px)) = &p.to {
                m.insert(
                    Value::String("to".into()),
                    Value::String(format!("{}/{}", n, px)),
                );
            }
            if let Some(t) = &p.table {
                m.insert(Value::String("table".into()), Value::String(resolve_t(t)?));
            }
            if !m.is_empty() {
                policy_seq.push(Value::Mapping(m));
            }
        }
        if !policy_seq.is_empty() {
            dev_cfg.insert(
                Value::String("routing-policy".into()),
                Value::Sequence(policy_seq),
            );
        }
    }
    let mut dns_list = Vec::new();
    if let Some(v4f) = &cfg.v4 {
        for d in &v4f.dns {
            dns_list.push(Value::String(d.clone()));
        }
    }
    if let Some(v6f) = &cfg.v6 {
        for d in &v6f.dns {
            dns_list.push(Value::String(d.clone()));
        }
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

fn run_netplan_apply(env: &mut dyn Env) -> Result<(), String> {
    let out = env.run("netplan", &["apply"]);
    if !out.ok {
        return Err(format!("`netplan apply` failed{}", out.detail()));
    }
    // netplan apply 有时退出码为 0 但把错误打在 stderr：仍然视为失败
    let stderr = out.stderr;
    let bad: Vec<&str> = stderr
        .lines()
        .filter(|l| l.starts_with("Error") || l.contains("Conflicting default route"))
        .collect();
    if !bad.is_empty() {
        return Err(format!(
            "`netplan apply` reported error: {}",
            bad.join("; ")
        ));
    }
    Ok(())
}

fn configure_with_netplan(cfg: &Config, env: &mut dyn Env) -> Result<(), String> {
    let file_path = select_netplan_file(env);

    // 先快照：读不到原配置就拒绝继续，绝不覆盖
    let snap = snapshot(env, &file_path)?;
    let content = match &snap {
        Snapshot::Present(c) => c.clone(),
        // 本后端只更新已有 netplan 配置，不凭空新建 yaml（避免与其它 yaml 争抢同设备）
        Snapshot::Missing => return Err(format!("netplan config {} not found", file_path)),
    };

    // C5:与 networkd/nmcli/ip 对齐,多默认网关时告警
    warn_extra_routes(env, cfg);

    let rt = load_rt_tables(env);
    let new_content = netplan_render(cfg, &content, &file_path, &rt)?;
    let bak = write_backup(env, &file_path, &snap)?;

    if let Err(e) = env.write(&file_path, &new_content) {
        // 写入失败（可能已截断）：用本次快照恢复
        return match restore_snapshot(env, &file_path, &snap) {
            Ok(()) => Err(format!(
                "failed to write {}: {}; restored from this run's snapshot",
                file_path, e
            )),
            Err(re) => Err(format!(
                "failed to write {}: {}; restore also failed: {}",
                file_path, e, re
            )),
        };
    }
    env.say(&format!(
        "[INFO] Wrote {}{}",
        file_path,
        bak.as_deref()
            .map(|b| format!(" (backup at {})", b))
            .unwrap_or_default()
    ));

    if let Err(e) = run_netplan_apply(env) {
        let rb = restore_snapshot(env, &file_path, &snap);
        // 让回滚后的配置重新生效（best-effort，结果已在下面的消息里区分）
        let reapplied = run_netplan_apply(env);
        return match (rb, reapplied) {
            (Ok(()), Ok(())) => Err(format!(
                "{}; rolled back {} from this run's snapshot and re-applied",
                e, file_path
            )),
            (Ok(()), Err(e2)) => Err(format!(
                "{}; rolled back {} but re-apply failed: {}",
                e, file_path, e2
            )),
            (Err(re), _) => Err(format!("{}; rollback failed: {}", e, re)),
        };
    }
    env.say("[INFO] Netplan configuration applied successfully");
    Ok(())
}

/// 解析 /etc/iproute2/rt_tables,返回 表名→数字id 的映射
fn load_rt_tables(env: &mut dyn Env) -> HashMap<String, u32> {
    let mut map = HashMap::new();
    if let Ok(content) = env.read("/etc/iproute2/rt_tables") {
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
fn resolve_table_id(t: &str, allocated: &mut HashMap<String, u32>) -> (u32, bool) {
    if let Ok(n) = t.parse::<u32>() {
        // 注册进 allocated,避免后续表名自动分配与此数字撞 id
        allocated.entry(t.to_string()).or_insert(n);
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
fn writeback_rt_tables(
    env: &mut dyn Env,
    allocated: &HashMap<String, u32>,
    initial: &HashMap<String, u32>,
) -> Result<(), String> {
    let path = "/etc/iproute2/rt_tables";
    let mut existing = initial.clone();
    let mut base_text = String::new();
    if env.exists(path) {
        base_text = env
            .read(path)
            .map_err(|e| format!("cannot read {}: {}", path, e))?;
        for line in base_text.lines() {
            let line = line.trim();
            if line.is_empty() || line.starts_with('#') {
                continue;
            }
            let parts: Vec<&str> = line.split_whitespace().collect();
            if parts.len() >= 2 {
                if let Ok(id) = parts[0].parse::<u32>() {
                    existing.insert(parts[1].to_string(), id);
                }
            }
        }
    }
    let mut to_write: Vec<(u32, String)> = allocated
        .iter()
        .filter(|(name, _)| name.parse::<u32>().is_err() && !existing.contains_key(*name))
        .map(|(name, &id)| (id, name.clone()))
        .collect();
    to_write.sort_by_key(|(id, _)| *id);
    if to_write.is_empty() {
        return Ok(());
    }
    if !base_text.is_empty() && !base_text.ends_with('\n') {
        base_text.push('\n');
    }
    for (id, name) in &to_write {
        base_text.push_str(&format!("{} {}\n", id, name));
    }
    env.write(path, &base_text)
        .map_err(|e| format!("cannot write {}: {}", path, e))
}

// ============ nmcli 后端 ============

/// 一条 NM 连接的最小标识（用于按 UUID 区分新旧 profile）
#[derive(Debug, Clone, PartialEq)]
struct NmConn {
    uuid: String,
    name: String,
    con_type: String,
}

/// 解析 `nmcli -t` 的转义输出：`\:` 表示字段内的冒号，`\\` 表示反斜杠
fn split_terse(line: &str) -> Vec<String> {
    let mut out: Vec<String> = Vec::new();
    let mut cur = String::new();
    let mut esc = false;
    for ch in line.chars() {
        if esc {
            cur.push(ch);
            esc = false;
        } else if ch == '\\' {
            esc = true;
        } else if ch == ':' {
            out.push(std::mem::take(&mut cur));
        } else {
            cur.push(ch);
        }
    }
    out.push(cur);
    out
}

fn parse_terse_conns(text: &str) -> Vec<NmConn> {
    let mut out = Vec::new();
    for line in text.lines() {
        if line.trim().is_empty() {
            continue;
        }
        let f = split_terse(line);
        if f.len() < 3 {
            continue;
        }
        out.push(NmConn {
            uuid: f[0].clone(),
            name: f[1].clone(),
            con_type: f[2].clone(),
        });
    }
    out
}

fn nm_connections(env: &mut dyn Env) -> Result<Vec<NmConn>, String> {
    let out = env.run("nmcli", &["-t", "-f", "UUID,NAME,TYPE", "con", "show"]);
    if !out.ok {
        return Err(format!(
            "`nmcli -t -f UUID,NAME,TYPE con show` failed{}; 无法确认现有连接，未做任何改动",
            out.detail()
        ));
    }
    Ok(parse_terse_conns(&out.stdout))
}

/// 查询连接绑定的接口名；查不到（命令失败/未设置）返回 None
fn nm_ifname_of(env: &mut dyn Env, uuid: &str) -> Option<String> {
    let out = env.run(
        "nmcli",
        &["-g", "connection.interface-name", "con", "show", uuid],
    );
    if !out.ok {
        return None;
    }
    for line in out.stdout.lines() {
        let l = line.trim();
        if l.is_empty() {
            continue;
        }
        let v = l
            .strip_prefix("connection.interface-name:")
            .unwrap_or(l)
            .trim();
        if !v.is_empty() {
            return Some(v.to_string());
        }
    }
    None
}

fn nmcli_render(cfg: &Config, allocated: &mut HashMap<String, u32>) -> Vec<String> {
    let con_name = format!("static-{}", &cfg.net_device);
    let mut args: Vec<String> = vec![
        "con".into(),
        "add".into(),
        "type".into(),
        "ethernet".into(),
        "ifname".into(),
        cfg.net_device.clone().into(),
        "con-name".into(),
        con_name.clone().into(),
        "connection.autoconnect-priority".into(),
        "10".into(),
    ];

    if let Some(v4f) = &cfg.v4 {
        if v4f.is_dhcp {
            args.push("ipv4.method".into());
            args.push("auto".into());
            if !v4f.dns.is_empty() {
                args.push("ipv4.dns".into());
                args.push(v4f.dns.join(","));
            }
        } else if !v4f.addrs.is_empty() {
            let addrs: Vec<String> = v4f
                .addrs
                .iter()
                .map(|(a, p)| format!("{}/{}", a, p))
                .collect();
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
            if !v4f.dns.is_empty() {
                args.push("ipv4.dns".into());
                args.push(v4f.dns.join(","));
            }
        }
    }
    if let Some(v6f) = &cfg.v6 {
        if v6f.is_dhcp {
            args.push("ipv6.method".into());
            args.push("auto".into());
            if !v6f.dns.is_empty() {
                args.push("ipv6.dns".into());
                args.push(v6f.dns.join(","));
            }
        } else if !v6f.addrs.is_empty() {
            let addrs: Vec<String> = v6f
                .addrs
                .iter()
                .map(|(a, p)| format!("{}/{}", a, p))
                .collect();
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
            if !v6f.dns.is_empty() {
                args.push("ipv6.dns".into());
                args.push(v6f.dns.join(","));
            }
        }
    } else {
        // 缺席的 family 显式 disabled,避免 nmcli 默认 method=auto 意外启用 DHCP/SLAAC
        args.push("ipv6.method".into());
        args.push("disabled".into());
    }
    if cfg.v4.is_none() {
        args.push("ipv4.method".into());
        args.push("disabled".into());
    }
    // A4:路由 table=表名 → 数字 id
    if !cfg.routes.is_empty() {
        let entries: Vec<String> = cfg
            .routes
            .iter()
            .map(|r| {
                let mut e = format!("{}/{}", r.to, r.to_prefix);
                if let Some(via) = &r.via {
                    e.push_str(&format!(" {}", via));
                }
                if let Some(t) = &r.table {
                    let (tid, _) = resolve_table_id(t, allocated);
                    e.push_str(&format!(" table={}", tid));
                }
                e
            })
            .collect();
        args.push("ipv4.routes".into());
        args.push(entries.join(","));
    }
    // A1+A3:routing-rules,表名→id,from+to 单条
    if !cfg.policies.is_empty() {
        let mut rules: Vec<String> = Vec::new();
        let mut prio = 32760u32;
        for p in &cfg.policies {
            let t = p.table.as_deref().unwrap_or("");
            if t.is_empty() {
                continue;
            }
            let tid = match t.parse::<u32>() {
                Ok(n) => n,
                Err(_) => {
                    let (id, alloced) = resolve_table_id(t, allocated);
                    if alloced {
                        eprintln!(
                            "[INFO] nmcli: auto-assigned table id {} for name '{}'",
                            id, t
                        );
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
            if prio > 100 {
                prio -= 1;
            }
        }
        if !rules.is_empty() {
            args.push("ipv4.routing-rules".into());
            args.push(rules.join(","));
        }
    }
    args
}

/// NM 后端：以 UUID 明确区分新旧 profile。
///
/// NM 要求 con-name 唯一，因此若按最终名 `static-<dev>` 直接 add，会与旧 profile 冲突；
/// 而先删旧 profile 又违背“任何失败都不丢旧配置”。折中做法：
///   1. 新 profile 先以临时名 `static-<dev>.bmip-new` 创建；
///   2. 用去程/回程两次 `con show` 的 UUID 差集确定新连接，按 UUID 激活；
///   3. 激活成功后按 UUID 删除本工具旧 profile，再把新连接改名为最终名。
/// 任何一步失败，旧 profile 都还在，且从未被修改。
fn configure_with_nmcli(cfg: &Config, env: &mut dyn Env) -> Result<(), String> {
    let con_name = format!("static-{}", cfg.net_device);
    let tmp_name = format!("{}.bmip-new", con_name);
    let dev = cfg.net_device.clone();

    // 1) 前置准备（无副作用）：现状查询失败就不动配置
    warn_extra_routes(env, cfg);
    let before = nm_connections(env)?;

    // 本工具的旧连接 = 名称精确等于 static-<dev> 且接口名确为本设备。
    // 不按模糊/前缀同名删除，也不碰其它接口或非本工具创建的 profile。
    let mut old_managed: Vec<String> = Vec::new();
    for c in &before {
        if c.name != con_name {
            continue;
        }
        match nm_ifname_of(env, &c.uuid) {
            Some(ifname) if ifname == dev => old_managed.push(c.uuid.clone()),
            Some(other) => env.say(&format!(
                "[WARNING] connection '{}' (uuid {}) has this tool's name but is bound to '{}', not '{}'; keeping it untouched",
                c.name, c.uuid, other, dev
            )),
            None => env.say(&format!(
                "[WARNING] cannot verify interface of connection '{}' (uuid {}); keeping it untouched to avoid breaking other interfaces",
                c.name, c.uuid
            )),
        }
    }

    // 上次运行中断可能留下的临时 profile：按名字 + 接口名确认是自己的才清掉
    for c in &before {
        if c.name == tmp_name && nm_ifname_of(env, &c.uuid).as_deref() == Some(dev.as_str()) {
            let d = env.run("nmcli", &["con", "delete", c.uuid.as_str()]);
            if !d.ok {
                return Err(format!(
                    "cannot remove leftover temporary profile '{}' ({}){}; nothing was changed",
                    tmp_name,
                    c.uuid,
                    d.detail()
                ));
            }
        }
    }

    let initial = load_rt_tables(env);
    let mut allocated = initial.clone();
    // 渲染时用最终名生成参数，再把 con-name 换成临时名提交
    let add_args = nmcli_render(cfg, &mut allocated);
    let add_args: Vec<String> = add_args
        .into_iter()
        .map(|a| if a == con_name { tmp_name.clone() } else { a })
        .collect();
    let add_refs: Vec<&str> = add_args.iter().map(String::as_str).collect();

    // 2) 以临时名新建连接；失败立即返回，旧配置完全未被触碰
    let add_out = env.run("nmcli", &add_refs);
    if !add_out.ok {
        return Err(format!(
            "nmcli con add '{}' failed{}; no existing connection was touched",
            tmp_name,
            add_out.detail()
        ));
    }

    // 3) 用 UUID 差集明确标识本次新建的连接（不按同名猜测）
    let after = match nm_connections(env) {
        Ok(v) => v,
        Err(e) => {
            return Err(format!(
                "{}; 无法确认新建连接的 UUID，已保留全部既有配置，请手工 `nmcli con show` 检查（临时 profile '{}' 可能残留）",
                e, tmp_name
            ));
        }
    };
    let created: Vec<&NmConn> = after
        .iter()
        .filter(|c| !before.iter().any(|b| b.uuid == c.uuid))
        .collect();
    if created.len() != 1 {
        return Err(format!(
            "cannot identify the newly created connection after `nmcli con add` ({} new uuid(s)); existing connections were left untouched",
            created.len()
        ));
    }
    let new_uuid = created[0].uuid.clone();

    // 4) 按 UUID 激活新连接；失败撤销本次新建，旧 profile 仍保持原状
    let up_out = env.run("nmcli", &["con", "up", new_uuid.as_str()]);
    if !up_out.ok {
        let del = env.run("nmcli", &["con", "delete", new_uuid.as_str()]);
        let mut msg = format!(
            "nmcli con up {} failed{}; the new profile was removed and the previous configuration was left untouched",
            new_uuid,
            up_out.detail()
        );
        if !del.ok {
            msg.push_str(&format!(
                "; additionally the temporary profile {} could not be removed{}",
                new_uuid,
                del.detail()
            ));
        }
        return Err(msg);
    }

    // 5) 新连接已激活，才清理本工具的旧托管 profile（按 UUID 逐个删除）
    for old in &old_managed {
        let d = env.run("nmcli", &["con", "delete", old.as_str()]);
        if !d.ok {
            // 非致命：新配置已生效，旧 profile 残留只影响后续同名解析
            env.say(&format!(
                "[WARNING] new connection is active, but deleting stale profile {} failed{}; remove it manually with `nmcli con delete {}`",
                old,
                d.detail(),
                old
            ));
        }
    }

    // 6) 把新连接改名为最终名（旧 profile 已让位），保证下次运行仍按 static-<dev> 识别
    let ren = env.run(
        "nmcli",
        &[
            "con",
            "modify",
            new_uuid.as_str(),
            "connection.id",
            con_name.as_str(),
        ],
    );
    if !ren.ok {
        // 非致命：配置已生效，只是名字不是最终名；下次运行会因名字不匹配而额外创建一个
        env.say(&format!(
            "[WARNING] connection is active but renaming {} to '{}' failed{}; rename it manually with `nmcli con modify {} connection.id {}`",
            new_uuid,
            con_name,
            ren.detail(),
            new_uuid,
            con_name
        ));
    }

    // 7) 表 id 回写。非致命：连接已按数字 id 生效，回写只影响后续复用同一表名。
    if let Err(e) = writeback_rt_tables(env, &allocated, &initial) {
        env.say(&format!(
            "[WARNING] {}; connection is active, only the table-name mapping was not persisted",
            e
        ));
    }

    env.say(&format!(
        "[INFO] nmcli configuration applied successfully (connection uuid {})",
        new_uuid
    ));
    Ok(())
}

// ============ systemd-networkd 后端 ============

fn networkd_render(cfg: &Config) -> (String, String) {
    let file_path = format!("/etc/systemd/network/10-{}.network", cfg.net_device);
    let mut s = String::new();
    s.push_str("[Match]\n");
    s.push_str(&format!("Name={}\n\n", cfg.net_device));
    s.push_str("[Network]\n");
    // DHCP= 是单值选项:先收集 v4/v6 是否 dhcp,再统一写一行(双 dhcp → yes)
    let v4_dhcp = cfg.v4.as_ref().map(|f| f.is_dhcp).unwrap_or(false);
    let v6_dhcp = cfg.v6.as_ref().map(|f| f.is_dhcp).unwrap_or(false);
    if v4_dhcp && v6_dhcp {
        s.push_str("DHCP=yes\n");
    } else if v4_dhcp {
        s.push_str("DHCP=ipv4\n");
    } else if v6_dhcp {
        s.push_str("DHCP=ipv6\n");
    }
    if let Some(v4f) = &cfg.v4 {
        if !v4f.is_dhcp {
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
        if !v6f.is_dhcp {
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
        for d in &v4f.dns {
            dns_list.push(d.clone());
        }
    }
    if let Some(v6f) = &cfg.v6 {
        for d in &v6f.dns {
            dns_list.push(d.clone());
        }
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

/// 重新加载并让配置生效。reconfigure 是关键命令，失败必须上报。
fn networkd_apply(env: &mut dyn Env, dev: &str) -> Result<(), String> {
    // reload 只刷新 networkd 的配置缓存；即便失败，reconfigure 也会重新读取文件，
    // 因此这里只告警，不作为失败（有意的非致命提示）。
    let reload = env.run("networkctl", &["reload"]);
    if !reload.ok {
        env.say(&format!(
            "[WARNING] `networkctl reload` failed{}; relying on reconfigure to re-read the file",
            reload.detail()
        ));
    }
    let rc = env.run("networkctl", &["reconfigure", dev]);
    if rc.ok {
        return Ok(());
    }
    // networkctl 不可用时回退重启 networkd（历史行为，保留）
    if !env.which("networkctl") {
        env.say("[WARNING] networkctl unavailable, falling back to restart systemd-networkd");
        return run_checked(env, "systemctl", &["restart", "systemd-networkd"]);
    }
    Err(format!(
        "`networkctl reconfigure {}` failed{}",
        dev,
        rc.detail()
    ))
}

fn configure_with_networkd(cfg: &Config, env: &mut dyn Env) -> Result<(), String> {
    // C5:与 netplan/nmcli/ip 对齐,多默认网关时告警
    warn_extra_routes(env, cfg);

    let (file_path, content) = networkd_render(cfg);

    // 写前快照：明确原文件存在/不存在；读不到就拒绝修改
    let snap = snapshot(env, &file_path)?;
    let bak = write_backup(env, &file_path, &snap)?;

    if let Err(e) = env.write(&file_path, &content) {
        return match restore_snapshot(env, &file_path, &snap) {
            Ok(()) => Err(format!(
                "failed to write {}: {}; restored from this run's snapshot",
                file_path, e
            )),
            Err(re) => Err(format!(
                "failed to write {}: {}; restore also failed: {}",
                file_path, e, re
            )),
        };
    }
    env.say(&format!(
        "[INFO] Created systemd-networkd config at {}{}",
        file_path,
        bak.as_deref()
            .map(|b| format!(" (backup at {})", b))
            .unwrap_or_default()
    ));

    if let Err(e) = networkd_apply(env, &cfg.net_device) {
        let rb = restore_snapshot(env, &file_path, &snap);
        let reapplied = networkd_apply(env, &cfg.net_device);
        return match (rb, reapplied) {
            (Ok(()), Ok(())) => Err(format!(
                "{}; rolled back {} from this run's snapshot and re-applied",
                e, file_path
            )),
            (Ok(()), Err(e2)) => Err(format!(
                "{}; rolled back {} but re-apply failed: {}",
                e, file_path, e2
            )),
            (Err(re), _) => Err(format!("{}; rollback failed: {}", e, re)),
        };
    }
    env.say("[INFO] systemd-networkd configuration applied successfully");
    Ok(())
}

// ============ ip 兜底后端 ============

/// 返回当前 main 表默认路由所在设备(解析 `ip route show default` 的 `dev X`)
fn default_route_dev(env: &mut dyn Env) -> Option<String> {
    let out = env.run("ip", &["route", "show", "default"]);
    if !out.ok {
        return None;
    }
    for line in out.stdout.lines() {
        if line.starts_with("default ") {
            let mut iter = line.split_whitespace();
            while let Some(tok) = iter.next() {
                if tok == "dev" {
                    return iter.next().map(|x| x.to_string());
                }
            }
        }
    }
    None
}

/// 生成 ip 兜底要执行的命令参数序列(纯函数,不执行)
fn ip_render(cfg: &Config) -> Vec<Vec<String>> {
    let mut cmds: Vec<Vec<String>> = Vec::new();
    cmds.push(vec![
        "addr".into(),
        "flush".into(),
        "dev".into(),
        cfg.net_device.clone(),
    ]);
    cmds.push(vec![
        "link".into(),
        "set".into(),
        "dev".into(),
        cfg.net_device.clone(),
        "up".into(),
    ]);
    if let Some(v4f) = &cfg.v4 {
        for (a, p) in &v4f.addrs {
            cmds.push(vec![
                "addr".into(),
                "add".into(),
                format!("{}/{}", a, p),
                "dev".into(),
                cfg.net_device.clone(),
            ]);
        }
        if let Some(gw) = &v4f.gateway {
            if !gw.is_empty() {
                cmds.push(vec![
                    "route".into(),
                    "add".into(),
                    "default".into(),
                    "via".into(),
                    gw.clone(),
                    "dev".into(),
                    cfg.net_device.clone(),
                ]);
            }
        }
    }
    if let Some(v6f) = &cfg.v6 {
        for (a, p) in &v6f.addrs {
            cmds.push(vec![
                "addr".into(),
                "add".into(),
                format!("{}/{}", a, p),
                "dev".into(),
                cfg.net_device.clone(),
            ]);
        }
        if let Some(gw) = &v6f.gateway {
            if !gw.is_empty() {
                cmds.push(vec![
                    "-6".into(),
                    "route".into(),
                    "add".into(),
                    "default".into(),
                    "via".into(),
                    gw.clone(),
                    "dev".into(),
                    cfg.net_device.clone(),
                ]);
            }
        }
    }
    for r in &cfg.routes {
        let mut c: Vec<String> = vec![
            "route".into(),
            "add".into(),
            format!("{}/{}", r.to, r.to_prefix),
        ];
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
    cmds.push(vec![
        "link".into(),
        "set".into(),
        "dev".into(),
        cfg.net_device.clone(),
        "up".into(),
    ]);
    cmds
}

fn collect_dns(cfg: &Config) -> Vec<String> {
    let mut out: Vec<String> = Vec::new();
    for fam in [cfg.v4.as_ref(), cfg.v6.as_ref()].into_iter().flatten() {
        for d in &fam.dns {
            if !d.is_empty() && !out.contains(d) {
                out.push(d.clone());
            }
        }
    }
    out
}

fn configure_with_ip(cfg: &Config, env: &mut dyn Env) -> Result<(), String> {
    let any_dhcp = cfg.v4.as_ref().map(|f| f.is_dhcp).unwrap_or(false)
        || cfg.v6.as_ref().map(|f| f.is_dhcp).unwrap_or(false);
    if any_dhcp {
        return Err("DHCP is not supported when using manual IP configuration".into());
    }

    // 1) 管理口保护必须早于任何写入（包含 DNS），否则拒绝时已经产生副作用
    if !cfg.force {
        if let Some(dev) = default_route_dev(env) {
            if dev == cfg.net_device {
                return Err(format!(
                    "refusing to flush {}: it carries the default route (likely management iface); use --force to override",
                    cfg.net_device
                ));
            }
        }
    }

    // C5:与 netplan/networkd/nmcli 对齐,多默认网关时告警
    warn_extra_routes(env, cfg);

    // 2) 执行 ip 命令。flush/link 失败立即中止（设备已不可用），
    //    地址/路由/规则失败继续跑完收集全部失败后再统一非零退出。
    let cmds = ip_render(cfg);
    let dev = cfg.net_device.clone();
    let mut failures: Vec<String> = Vec::new();
    let mut addr_ok = 0usize;
    let mut addr_total = 0usize;

    for c in &cmds {
        let refs: Vec<&str> = c.iter().map(String::as_str).collect();
        let is_flush = c.len() >= 2 && c[0] == "addr" && c[1] == "flush";
        let is_link = c[0] == "link";
        let is_addr_add = c.len() >= 2 && c[0] == "addr" && c[1] == "add";

        let out = env.run("ip", &refs);
        if is_addr_add {
            addr_total += 1;
        }
        if out.ok {
            if is_addr_add {
                addr_ok += 1;
            }
            continue;
        }
        let msg = format!("[ERROR] `ip {}` failed{}", c.join(" "), out.detail());
        if is_flush || is_link {
            // 设备基础状态都没建立起来，继续执行没有意义
            return Err(format!("`ip {}` failed{}", c.join(" "), out.detail()));
        }
        failures.push(msg);
    }

    if addr_total > 0 && addr_ok < addr_total {
        failures.push(format!(
            "[ERROR] only {}/{} address(es) were added to {}",
            addr_ok, addr_total, dev
        ));
    }

    // 3) DNS 最后应用：地址配置自身失败时不再改动 DNS，避免把解析指向未配置的链路
    if failures.is_empty() {
        let dns_list = collect_dns(cfg);
        if !dns_list.is_empty() {
            if let Err(e) = apply_dns(env, &dev, &dns_list) {
                failures.push(format!("[ERROR] {}", e));
            }
        }
    }

    if !failures.is_empty() {
        return Err(failures.join("; "));
    }

    env.say(&format!(
        "[INFO] Manual IP configuration applied (addresses: {}/{})",
        addr_ok, addr_total
    ));
    Ok(())
}

/// 应用 DNS:优先 resolvconf(写完整 stdin 并检查退出码),其次 resolvectl(真实接口名 + 一次传全部),
/// 最后回退直写 /etc/resolv.conf(写前快照,失败传播)。
fn apply_dns(env: &mut dyn Env, dev: &str, servers: &[String]) -> Result<(), String> {
    let body: String = servers
        .iter()
        .map(|s| format!("nameserver {}\n", s))
        .collect();

    if env.which("resolvconf") {
        // 完整 stdin + 等待退出：resolvconf 从 stdin 读 nameserver
        let out = env.run_stdin("resolvconf", &["-a", dev], &body);
        if !out.ok {
            return Err(format!("`resolvconf -a {}` failed{}", dev, out.detail()));
        }
        env.say(&format!(
            "[INFO] Applied {} DNS server(s) via resolvconf on {}",
            servers.len(),
            dev
        ));
        return Ok(());
    }

    if env.which("resolvectl") {
        // 真实接口名 + 一次性传入全部 DNS（逐条调用会互相覆盖）
        let mut args: Vec<&str> = vec!["dns", dev];
        for s in servers {
            args.push(s.as_str());
        }
        let out = env.run("resolvectl", &args);
        if !out.ok {
            return Err(format!(
                "`resolvectl dns {} {}` failed{}",
                dev,
                servers.join(" "),
                out.detail()
            ));
        }
        env.say(&format!(
            "[INFO] Applied {} DNS server(s) via resolvectl on {}",
            servers.len(),
            dev
        ));
        return Ok(());
    }

    // 文件回退
    let path = "/etc/resolv.conf";
    let snap = snapshot(env, path)?;
    let bak = write_backup(env, path, &snap)?;
    if let Err(e) = env.write(path, &body) {
        let rb = restore_snapshot(env, path, &snap);
        return Err(match rb {
            Ok(()) => format!("failed to write {}: {}", path, e),
            Err(re) => format!(
                "failed to write {}: {}; restore also failed: {}",
                path, e, re
            ),
        });
    }
    env.say(&format!(
        "[INFO] Wrote {}{} ({} DNS server(s))",
        path,
        bak.as_deref()
            .map(|b| format!(" (backup at {})", b))
            .unwrap_or_default(),
        servers.len()
    ));
    Ok(())
}

// ============ 后端分发 ============

fn dispatch(cfg: &Config, nm: NetManager, env: &mut dyn Env) -> Result<(), String> {
    match nm {
        NetManager::Netplan => {
            env.say("[INFO] Using netplan for network configuration");
            configure_with_netplan(cfg, env)
        }
        NetManager::NetworkManager => {
            env.say("[INFO] Using NetworkManager (nmcli) for network configuration");
            configure_with_nmcli(cfg, env)
        }
        NetManager::SystemdNetworkd => {
            env.say("[INFO] Using systemd-networkd for network configuration");
            configure_with_networkd(cfg, env)
        }
        NetManager::Unknown => {
            // 原来是 [ERROR] 但仍继续并返回 0；改成 WARNING，失败一律走非零退出
            env.say("[WARNING] Could not detect a supported network manager! Trying to configure IP manually using ip command");
            configure_with_ip(cfg, env)
        }
    }
}

fn main() {
    // 版本信息固定为执行首行（MYS-809 发版规范：可执行文件首行即版本号）。
    // GIT_TAG_COMMIT 由 build.rs 注入（release.sh 传 BM_SET_IP_GIT_VERSION，回退
    // .git_version 文件），见 build.rs。
    println!("bm_set_ip version: {}", env!("GIT_TAG_COMMIT"));

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
        let exe = match env::current_exe() {
            Ok(e) => e,
            Err(e) => {
                eprintln!("[ERROR] cannot resolve current executable: {}", e);
                exit(1);
            }
        };
        let argv: Vec<String> = env::args().skip(1).collect();
        let status = match Command::new("sudo").arg(exe).args(&argv).status() {
            Ok(s) => s,
            Err(e) => {
                eprintln!("[ERROR] failed to execute sudo: {}", e);
                exit(1);
            }
        };
        exit(status.code().unwrap_or(1));
    }

    let mut net_env = OsEnv::new();
    let net_manager = detect_net_manager(&mut net_env);
    if let Err(e) = dispatch(&cfg, net_manager, &mut net_env) {
        eprintln!("[ERROR] {}", e);
        exit(1);
    }
}

// ============ 测试：stateful fake 后端 ============

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::{HashMap, HashSet, VecDeque};

    /// 有状态的 NM 连接模型（uuid 独立于名称，用于验证“按 UUID 区分新旧”）
    #[derive(Clone, Debug)]
    struct Conn {
        uuid: String,
        name: String,
        con_type: String,
        ifname: String,
    }

    struct Fake {
        files: HashMap<String, String>,
        dirs: HashMap<String, Vec<String>>,
        unreadable: HashSet<String>,
        unwritable: HashSet<String>,
        programs: HashSet<String>,
        nm: Vec<Conn>,
        nm_next: u32,
        /// 失败开关："add" / "show" / "up" / "up:<uuid>" / "delete:<uuid>"
        nm_fail: HashSet<String>,
        /// ip 命令失败前缀（如 "addr flush"）：命中即返回非零
        ip_fail: Vec<String>,
        ip_default_route: String,
        netplan_apply: VecDeque<Out>,
        netctl_reload: VecDeque<Out>,
        netctl_reconfigure: VecDeque<Out>,
        resolvconf: VecDeque<Out>,
        resolvectl: VecDeque<Out>,
        calls: Vec<String>,
        stdin_log: Vec<(String, String)>,
        said: Vec<String>,
    }

    impl Fake {
        fn new() -> Self {
            Fake {
                files: HashMap::new(),
                dirs: HashMap::new(),
                unreadable: HashSet::new(),
                unwritable: HashSet::new(),
                programs: HashSet::new(),
                nm: Vec::new(),
                nm_next: 0,
                nm_fail: HashSet::new(),
                ip_fail: Vec::new(),
                ip_default_route: "default via 192.0.2.1 dev eth9".to_string(),
                netplan_apply: VecDeque::new(),
                netctl_reload: VecDeque::new(),
                netctl_reconfigure: VecDeque::new(),
                resolvconf: VecDeque::new(),
                resolvectl: VecDeque::new(),
                calls: Vec::new(),
                stdin_log: Vec::new(),
                said: Vec::new(),
            }
        }

        fn file(mut self, path: &str, content: &str) -> Self {
            self.files.insert(path.to_string(), content.to_string());
            self
        }

        fn prog(mut self, name: &str) -> Self {
            self.programs.insert(name.to_string());
            self
        }

        fn conn(mut self, name: &str, ifname: &str) -> Self {
            let uuid = format!("uuid-legacy-{}", name);
            self.nm.push(Conn {
                uuid,
                name: name.to_string(),
                con_type: "802-3-ethernet".to_string(),
                ifname: ifname.to_string(),
            });
            self
        }

        fn calls_of(&self, prefix: &str) -> Vec<String> {
            self.calls
                .iter()
                .filter(|c| c.starts_with(prefix))
                .cloned()
                .collect()
        }

        /// 所有会改动系统的外部命令（用于断言“拒绝时零副作用”）
        fn mutating_calls(&self) -> Vec<String> {
            self.calls
                .iter()
                .filter(|c| {
                    c.starts_with("ip ") && !c.contains("route show")
                        || c.starts_with("nmcli con add")
                        || c.starts_with("nmcli con up")
                        || c.starts_with("nmcli con delete")
                        || c.starts_with("netplan apply")
                        || c.starts_with("networkctl reconfigure")
                        || c.starts_with("resolvconf")
                        || c.starts_with("resolvectl")
                })
                .cloned()
                .collect()
        }

        fn said(&self) -> String {
            self.said.join("\n")
        }

        fn conn_by_uuid(&self, uuid: &str) -> Option<&Conn> {
            self.nm.iter().find(|c| c.uuid == uuid)
        }
    }

    fn terse_escape(s: &str) -> String {
        s.replace('\\', "\\\\").replace(':', "\\:")
    }

    impl Env for Fake {
        fn which(&mut self, program: &str) -> bool {
            self.programs.contains(program)
        }

        fn run(&mut self, program: &str, args: &[&str]) -> Out {
            self.calls.push(format!("{} {}", program, args.join(" ")));
            match program {
                "nmcli" => self.nmcli(args),
                "ip" => {
                    let joined = args.join(" ");
                    if args == ["route", "show", "default"] {
                        return Out::ok_with(self.ip_default_route.clone());
                    }
                    if self.ip_fail.iter().any(|p| joined.starts_with(p.as_str())) {
                        return Out::fail_with("RTNETLINK answers: Operation not permitted");
                    }
                    Out::ok_with("")
                }
                "netplan" => self
                    .netplan_apply
                    .pop_front()
                    .unwrap_or_else(|| Out::ok_with("")),
                "networkctl" => match args.first().copied() {
                    Some("reload") => self
                        .netctl_reload
                        .pop_front()
                        .unwrap_or_else(|| Out::ok_with("")),
                    Some("reconfigure") => self
                        .netctl_reconfigure
                        .pop_front()
                        .unwrap_or_else(|| Out::ok_with("")),
                    _ => Out::ok_with(""),
                },
                "resolvconf" => self
                    .resolvconf
                    .pop_front()
                    .unwrap_or_else(|| Out::ok_with("")),
                "resolvectl" => self
                    .resolvectl
                    .pop_front()
                    .unwrap_or_else(|| Out::ok_with("")),
                _ => Out::ok_with(""),
            }
        }

        fn run_stdin(&mut self, program: &str, args: &[&str], input: &str) -> Out {
            self.calls
                .push(format!("{} {} <stdin>", program, args.join(" ")));
            self.stdin_log
                .push((format!("{} {}", program, args.join(" ")), input.to_string()));
            match program {
                "resolvconf" => self
                    .resolvconf
                    .pop_front()
                    .unwrap_or_else(|| Out::ok_with("")),
                "resolvectl" => self
                    .resolvectl
                    .pop_front()
                    .unwrap_or_else(|| Out::ok_with("")),
                _ => Out::ok_with(""),
            }
        }

        fn read(&mut self, path: &str) -> io::Result<String> {
            if self.unreadable.contains(path) {
                return Err(io::Error::new(
                    io::ErrorKind::PermissionDenied,
                    "permission denied",
                ));
            }
            self.files
                .get(path)
                .cloned()
                .ok_or_else(|| io::Error::new(io::ErrorKind::NotFound, "no such file"))
        }

        fn exists(&mut self, path: &str) -> bool {
            self.files.contains_key(path)
        }

        fn write(&mut self, path: &str, content: &str) -> io::Result<()> {
            if self.unwritable.contains(path) {
                return Err(io::Error::new(
                    io::ErrorKind::PermissionDenied,
                    "read-only file",
                ));
            }
            self.files.insert(path.to_string(), content.to_string());
            Ok(())
        }

        fn remove(&mut self, path: &str) -> io::Result<()> {
            match self.files.remove(path) {
                Some(_) => Ok(()),
                None => Ok(()),
            }
        }

        fn list_files(&mut self, dir: &str) -> Vec<String> {
            self.dirs.get(dir).cloned().unwrap_or_default()
        }

        fn say(&mut self, msg: &str) {
            self.said.push(msg.to_string());
        }
    }

    impl Fake {
        fn nmcli(&mut self, args: &[&str]) -> Out {
            // nmcli -t -f UUID,NAME,TYPE con show
            if args.len() >= 5 && args[0] == "-t" {
                if self.nm_fail.contains("show") {
                    return Out::fail_with("Error: NetworkManager is not running");
                }
                let mut s = String::new();
                for c in &self.nm {
                    s.push_str(&format!(
                        "{}:{}:{}\n",
                        terse_escape(&c.uuid),
                        terse_escape(&c.name),
                        terse_escape(&c.con_type)
                    ));
                }
                return Out::ok_with(s);
            }
            // nmcli -g connection.interface-name con show <uuid>
            if args.len() >= 5 && args[0] == "-g" {
                let target = args[4];
                return match self
                    .nm
                    .iter()
                    .find(|c| c.uuid == target || c.name == target)
                {
                    Some(c) => Out::ok_with(format!("connection.interface-name:{}\n", c.ifname)),
                    None => Out::fail_with("Error: unknown connection"),
                };
            }
            // nmcli con show <uuid>  —— 完整 profile dump（恢复用）
            if args.len() == 3 && args[0] == "con" && args[1] == "show" {
                let target = args[2];
                return match self
                    .nm
                    .iter()
                    .find(|c| c.uuid == target || c.name == target)
                {
                    Some(c) => Out::ok_with(format!(
                        "connection.id:                          {}\nconnection.uuid:                        {}\nconnection.type:                        802-3-ethernet\nconnection.interface-name:              {}\nipv4.method:                            manual\n",
                        c.name, c.uuid, c.ifname
                    )),
                    None => Out::fail_with("Error: unknown connection"),
                };
            }
            if args.len() >= 2 && args[0] == "con" && args[1] == "add" {
                if self.nm_fail.contains("add") {
                    return Out::fail_with("Error: failed to create connection: invalid property");
                }
                let mut ifname = String::new();
                let mut name = String::new();
                let mut i = 2;
                while i + 1 < args.len() {
                    match args[i] {
                        "ifname" => ifname = args[i + 1].to_string(),
                        "con-name" => name = args[i + 1].to_string(),
                        _ => {}
                    }
                    i += 1;
                }
                self.nm_next += 1;
                self.nm.push(Conn {
                    uuid: format!("uuid-new-{}", self.nm_next),
                    name,
                    con_type: "802-3-ethernet".to_string(),
                    ifname,
                });
                return Out::ok_with("Connection 'x' created");
            }
            if args.len() >= 3 && args[0] == "con" && args[1] == "up" {
                let target = args[2];
                if self.nm_fail.contains("up") || self.nm_fail.contains(&format!("up:{}", target)) {
                    return Out::fail_with(
                        "Error: Connection activation failed: No suitable device found",
                    );
                }
                return Out::ok_with("Connection successfully activated");
            }
            if args.len() >= 5 && args[0] == "con" && args[1] == "modify" {
                let target = args[2];
                if self.nm_fail.contains("modify")
                    || self.nm_fail.contains(&format!("modify:{}", target))
                {
                    return Out::fail_with("Error: failed to modify connection");
                }
                return match self.nm.iter_mut().find(|c| c.uuid == target) {
                    Some(c) => {
                        c.name = args[4].to_string();
                        Out::ok_with("Connection 'x' successfully modified.")
                    }
                    None => Out::fail_with("Error: unknown connection"),
                };
            }
            if args.len() >= 3 && args[0] == "con" && args[1] == "delete" {
                let target = args[2];
                if self.nm_fail.contains(&format!("delete:{}", target)) {
                    return Out::fail_with("Error: unknown connection");
                }
                self.nm.retain(|c| c.uuid != target && c.name != target);
                return Out::ok_with("Connection deleted");
            }
            Out::fail_with("Error: unsupported fake nmcli invocation")
        }
    }

    // ---------- 测试夹具 ----------

    fn cfg_v4(dev: &str, addrs: &[(&str, u8)], gw: Option<&str>, dns: &[&str]) -> Config {
        Config {
            net_device: dev.to_string(),
            family1_is_v6: false,
            v4: Some(Family {
                addrs: addrs.iter().map(|(a, p)| (a.to_string(), *p)).collect(),
                gateway: gw.map(|g| g.to_string()),
                dns: dns.iter().map(|d| d.to_string()).collect(),
                is_dhcp: false,
            }),
            v6: None,
            routes: vec![],
            policies: vec![],
            dry_run: false,
            force: false,
        }
    }

    fn nm_state(f: &Fake) -> Vec<(String, String, String)> {
        f.nm.iter()
            .map(|c| (c.uuid.clone(), c.name.clone(), c.ifname.clone()))
            .collect()
    }

    // ---------- NM：配置丢失 ----------

    #[test]
    fn nm_first_run_creates_and_activates_without_deleting_anything() {
        let mut f = Fake::new();
        let cfg = cfg_v4("eth1", &[("10.1.0.5", 24)], Some("10.1.0.1"), &[]);
        let r = configure_with_nmcli(&cfg, &mut f);
        assert!(r.is_ok(), "首次配置应成功: {:?}", r);

        // 首次没有旧连接：不得出现任何 delete
        assert!(
            f.calls_of("nmcli con delete").is_empty(),
            "首次不应删除连接: {:?}",
            f.calls
        );
        // 且激活用的是新建连接的 UUID，而不是同名猜测
        let ups = f.calls_of("nmcli con up");
        assert_eq!(
            ups,
            vec!["nmcli con up uuid-new-1"],
            "应按 UUID 激活新连接: {:?}",
            f.calls
        );
        // 激活后改名为最终名，便于下次运行识别
        assert!(
            f.calls
                .iter()
                .any(|c| c == "nmcli con modify uuid-new-1 connection.id static-eth1"),
            "应按 UUID 把新连接改名为最终名: {:?}",
            f.calls
        );
        assert_eq!(
            nm_state(&f).len(),
            1,
            "应只留下一个连接: {:?}",
            nm_state(&f)
        );
        assert!(
            f.said().contains("applied successfully"),
            "成功路径应有成功文案"
        );
    }

    #[test]
    fn nm_same_name_old_connection_is_removed_only_after_new_is_active() {
        let mut f = Fake::new().conn("static-eth1", "eth1");
        let cfg = cfg_v4("eth1", &[("10.1.0.5", 24)], Some("10.1.0.1"), &[]);
        let r = configure_with_nmcli(&cfg, &mut f);
        assert!(r.is_ok(), "修复后应成功: {:?}", r);

        // 旧连接被删除，新连接保留 —— 原代码 delete 同名会把新连接删掉
        let deletes = f.calls_of("nmcli con delete");
        assert_eq!(
            deletes,
            vec!["nmcli con delete uuid-legacy-static-eth1"],
            "只应删除旧 UUID: {:?}",
            deletes
        );
        assert!(
            f.conn_by_uuid("uuid-new-1").is_some(),
            "新连接必须留存: {:?}",
            nm_state(&f)
        );
        assert!(
            f.conn_by_uuid("uuid-legacy-static-eth1").is_none(),
            "旧连接应被清理"
        );

        // 顺序：add -> up(新UUID) -> delete(旧UUID) -> modify(改名)
        let add_at = f
            .calls
            .iter()
            .position(|c| c.starts_with("nmcli con add"))
            .unwrap();
        let up_at = f
            .calls
            .iter()
            .position(|c| c == "nmcli con up uuid-new-1")
            .unwrap();
        let del_at = f
            .calls
            .iter()
            .position(|c| c == "nmcli con delete uuid-legacy-static-eth1")
            .unwrap();
        let ren_at = f
            .calls
            .iter()
            .position(|c| c == "nmcli con modify uuid-new-1 connection.id static-eth1")
            .unwrap();
        assert!(
            add_at < up_at && up_at < del_at && del_at < ren_at,
            "顺序必须 add < up < delete < modify: {:?}",
            f.calls
        );
        // 新 profile 先以临时名创建，避免与旧 profile 的 con-name 冲突
        assert!(
            f.calls
                .iter()
                .any(|c| c.starts_with("nmcli con add") && c.contains("static-eth1.bmip-new")),
            "应先以临时名创建: {:?}",
            f.calls
        );
        assert_eq!(
            f.nm.iter()
                .find(|c| c.uuid == "uuid-new-1")
                .map(|c| c.name.clone()),
            Some("static-eth1".to_string()),
            "最终名应为 static-eth1"
        );
    }

    #[test]
    fn nm_add_failure_is_nonzero_and_keeps_old_connection() {
        let mut f = Fake::new().conn("static-eth1", "eth1");
        f.nm_fail.insert("add".into());
        let cfg = cfg_v4("eth1", &[("10.1.0.5", 24)], None, &[]);
        let r = configure_with_nmcli(&cfg, &mut f);

        assert!(r.is_err(), "add 失败必须返回错误（原来直接 return）");
        assert!(
            f.calls_of("nmcli con delete").is_empty(),
            "add 失败不得删除旧连接: {:?}",
            f.calls
        );
        assert!(
            f.conn_by_uuid("uuid-legacy-static-eth1").is_some(),
            "旧配置必须保留"
        );
        // 错误文案经 main 打出（said 只记录 say() 的 INFO/WARNING），这里断言返回值
        assert!(
            r.as_ref()
                .unwrap_err()
                .contains("no existing connection was touched"),
            "应说明旧配置未被改动: {:?}",
            r
        );
        assert!(
            f.calls_of("nmcli con up").is_empty(),
            "add 失败不应激活任何连接"
        );
        assert!(
            f.conn_by_uuid("uuid-legacy-static-eth1").is_some(),
            "旧配置必须保留"
        );
        assert!(
            !f.said().contains("applied successfully"),
            "失败不得输出成功文案"
        );
    }

    #[test]
    fn nm_up_failure_is_nonzero_removes_new_and_reactivates_old() {
        let mut f = Fake::new().conn("static-eth1", "eth1");
        f.nm_fail.insert("up:uuid-new-1".into());
        let cfg = cfg_v4("eth1", &[("10.1.0.5", 24)], None, &[]);
        let r = configure_with_nmcli(&cfg, &mut f);

        assert!(r.is_err(), "up 失败必须非零");
        assert!(
            f.conn_by_uuid("uuid-new-1").is_none(),
            "失败的半成品连接应撤销"
        );
        assert!(
            f.conn_by_uuid("uuid-legacy-static-eth1").is_some(),
            "旧连接不得丢失"
        );
        // 新 profile 用的是临时名，旧 profile 从未被删除，因此也无需（且不能）重建
        assert!(
            !f.calls_of("nmcli con delete")
                .iter()
                .any(|c| c == "nmcli con delete uuid-legacy-static-eth1"),
            "旧连接不得被删除: {:?}",
            f.calls
        );
        assert!(
            !f.said().contains("applied successfully"),
            "失败不得输出成功文案"
        );
    }

    #[test]
    fn nm_leaves_other_interfaces_and_unmanaged_connections_untouched() {
        let mut f = Fake::new()
            // 同名但绑定在别的接口：不得按名称模糊删除
            .conn("static-eth1", "eth2")
            // 非本工具创建的连接
            .conn("Wired connection 1", "eth0");
        let cfg = cfg_v4("eth1", &[("10.1.0.5", 24)], None, &[]);
        let r = configure_with_nmcli(&cfg, &mut f);

        assert!(r.is_ok(), "应成功: {:?}", r);
        assert!(
            f.calls_of("nmcli con delete").is_empty(),
            "不得删除其它接口/非托管连接: {:?}",
            f.calls
        );
        assert!(
            f.conn_by_uuid("uuid-legacy-static-eth1").is_some(),
            "绑定 eth2 的同名连接必须保留"
        );
        assert!(
            f.conn_by_uuid("uuid-legacy-Wired connection 1").is_some(),
            "非托管连接必须保留"
        );
        assert!(
            f.said().contains("bound to 'eth2'"),
            "应给出绑定接口不符的告警: {}",
            f.said()
        );
    }

    #[test]
    fn nm_show_failure_aborts_without_touching_anything() {
        let mut f = Fake::new().conn("static-eth1", "eth1");
        f.nm_fail.insert("show".into());
        let cfg = cfg_v4("eth1", &[("10.1.0.5", 24)], None, &[]);
        let r = configure_with_nmcli(&cfg, &mut f);

        assert!(r.is_err(), "无法读取现有连接时应拒绝修改");
        assert!(
            f.calls_of("nmcli con add").is_empty(),
            "不得在状态未知时新增连接: {:?}",
            f.calls
        );
        assert!(f.conn_by_uuid("uuid-legacy-static-eth1").is_some());
    }

    #[test]
    fn nm_delete_failure_after_activation_is_nonfatal_warning() {
        // 新连接已生效，清理旧 profile 失败属于有意的非致命告警
        let mut f = Fake::new().conn("static-eth1", "eth1");
        f.nm_fail.insert("delete:uuid-legacy-static-eth1".into());
        let cfg = cfg_v4("eth1", &[("10.1.0.5", 24)], None, &[]);
        let r = configure_with_nmcli(&cfg, &mut f);

        assert!(r.is_ok(), "新配置已生效时清理失败不应整体失败: {:?}", r);
        assert!(
            f.said().contains("deleting stale profile"),
            "必须明确告警: {}",
            f.said()
        );
        assert!(
            f.said().contains("applied successfully"),
            "新配置确实已生效"
        );
        assert!(f.conn_by_uuid("uuid-new-1").is_some(), "新连接必须在用");
    }

    #[test]
    fn nm_rename_failure_after_activation_is_nonfatal_warning() {
        let mut f = Fake::new().conn("static-eth1", "eth1");
        f.nm_fail.insert("modify".into());
        let cfg = cfg_v4("eth1", &[("10.1.0.5", 24)], None, &[]);
        let r = configure_with_nmcli(&cfg, &mut f);

        assert!(r.is_ok(), "改名失败不应整体失败: {:?}", r);
        assert!(f.said().contains("renaming"), "必须明确告警: {}", f.said());
        assert!(f.said().contains("applied successfully"));
    }

    #[test]
    fn nm_removes_leftover_temporary_profile() {
        // 上次中断残留的临时 profile：按名字+接口确认后才清理，且不影响旧 profile
        let mut f = Fake::new().conn("static-eth1", "eth1");
        f.nm.push(Conn {
            uuid: "uuid-leftover-tmp".into(),
            name: "static-eth1.bmip-new".into(),
            con_type: "802-3-ethernet".into(),
            ifname: "eth1".into(),
        });
        let cfg = cfg_v4("eth1", &[("10.1.0.5", 24)], None, &[]);
        let r = configure_with_nmcli(&cfg, &mut f);
        assert!(r.is_ok(), "{:?}", r);
        assert!(
            f.conn_by_uuid("uuid-leftover-tmp").is_none(),
            "残留临时 profile 应被清理"
        );
        assert!(f.conn_by_uuid("uuid-new-1").is_some());
    }

    #[test]
    fn nm_replaces_previous_tool_profile_end_to_end() {
        // 模拟第二次运行：上一轮留下的 static-eth1（本工具、本接口）应被替换为新配置
        let mut f = Fake::new();
        f.nm.push(Conn {
            uuid: "uuid-prev".into(),
            name: "static-eth1".into(),
            con_type: "802-3-ethernet".into(),
            ifname: "eth1".into(),
        });
        let cfg = cfg_v4("eth1", &[("10.2.0.9", 24)], Some("10.2.0.1"), &[]);
        let r = configure_with_nmcli(&cfg, &mut f);
        assert!(r.is_ok(), "{:?}", r);
        assert!(
            f.conn_by_uuid("uuid-prev").is_none(),
            "上一轮的 profile 应被替换"
        );
        let live: Vec<&Conn> = f.nm.iter().collect();
        assert_eq!(live.len(), 1, "最终只应有一个连接: {:?}", nm_state(&f));
        assert_eq!(live[0].name, "static-eth1", "最终名应是 static-eth1");
    }

    // ---------- ip 后端：失败必须非零 ----------

    #[test]
    fn ip_flush_failure_is_nonzero_and_stops_before_addressing() {
        let mut f = Fake::new();
        f.ip_fail.push("addr flush".to_string());
        f.ip_default_route = "default via 192.0.2.1 dev eth9".to_string();
        let cfg = cfg_v4("eth1", &[("10.1.0.5", 24)], Some("10.1.0.1"), &[]);
        let r = configure_with_ip(&cfg, &mut f);

        assert!(r.is_err(), "flush 失败必须非零");
        assert!(
            f.calls_of("ip addr add").is_empty(),
            "设备不可用时不应继续加地址: {:?}",
            f.calls
        );
        assert!(!f.said().contains("applied"), "失败不得输出成功文案");
    }

    #[test]
    fn ip_partial_address_failure_is_nonzero() {
        let mut f = Fake::new();
        f.ip_fail.push("addr add 10.1.0.6".to_string());
        let cfg = cfg_v4("eth1", &[("10.1.0.5", 24), ("10.1.0.6", 24)], None, &[]);
        let r = configure_with_ip(&cfg, &mut f);

        let e = r.expect_err("部分地址失败必须非零");
        assert!(e.contains("1/2"), "错误应指明部分失败: {}", e);
        assert_eq!(f.calls_of("ip addr add").len(), 2, "两处地址都应尝试");
    }

    #[test]
    fn ip_route_and_rule_failures_are_nonzero() {
        let mut f = Fake::new();
        f.ip_fail.push("route add 10.20.0.0".to_string());
        let mut cfg = cfg_v4("eth1", &[("10.1.0.5", 24)], None, &[]);
        cfg.routes = vec![Route {
            to: "10.20.0.0".into(),
            to_prefix: 24,
            via: None,
            table: Some("100".into()),
        }];
        cfg.policies = vec![Policy {
            from: Some(("10.1.0.0".into(), 24)),
            to: None,
            table: Some("100".into()),
        }];
        let r = configure_with_ip(&cfg, &mut f);

        let e = r.expect_err("显式请求的路由失败必须非零");
        assert!(
            e.contains("route add 10.20.0.0/24"),
            "错误应包含失败命令: {}",
            e
        );
        // rule 不是失败项，应仍被执行
        assert_eq!(
            f.calls_of("ip rule add").len(),
            1,
            "非失败命令继续执行: {:?}",
            f.calls
        );
    }

    #[test]
    fn ip_dns_failure_is_nonzero() {
        let mut f = Fake::new().prog("resolvconf");
        f.resolvconf
            .push_back(Out::fail_with("resolvconf: cannot write"));
        let cfg = cfg_v4("eth1", &[("10.1.0.5", 24)], None, &["8.8.8.8"]);
        let r = configure_with_ip(&cfg, &mut f);

        let e = r.expect_err("DNS 失败必须非零");
        assert!(e.contains("resolvconf"), "错误应指明 DNS 后端: {}", e);
    }

    #[test]
    fn ip_management_guard_rejects_before_any_write_including_dns() {
        let mut f = Fake::new().prog("resolvconf").prog("resolvectl");
        // 默认路由就在目标接口上 —— 管理口保护必须拒绝
        f.ip_default_route = "default via 10.43.0.1 dev eth0 metric 100".to_string();
        let cfg = cfg_v4(
            "eth0",
            &[("10.43.0.157", 24)],
            Some("10.43.0.1"),
            &["8.8.8.8", "114.114.114.114"],
        );
        let r = configure_with_ip(&cfg, &mut f);

        assert!(r.is_err(), "管理口必须被拒绝");
        assert!(
            r.unwrap_err().contains("refusing to flush"),
            "应给出保护原因"
        );
        // 关键：拒绝时不得有任何写操作，DNS 也不能先被写（原代码先写 DNS）
        assert!(
            f.mutating_calls().is_empty(),
            "拒绝时必须零副作用: {:?}",
            f.mutating_calls()
        );
        assert!(
            f.stdin_log.is_empty(),
            "不得向 resolvconf 写入 stdin: {:?}",
            f.stdin_log
        );
        assert_eq!(f.calls_of("resolvectl").len(), 0, "不得调用 resolvectl");
    }

    #[test]
    fn ip_success_reports_all_addresses() {
        let mut f = Fake::new();
        let cfg = cfg_v4(
            "eth1",
            &[("10.1.0.5", 24), ("10.1.0.6", 24)],
            Some("10.1.0.1"),
            &[],
        );
        let r = configure_with_ip(&cfg, &mut f);
        assert!(r.is_ok(), "全部成功应 Ok: {:?}", r);
        assert!(
            f.said().contains("addresses: 2/2"),
            "成功文案应含计数: {}",
            f.said()
        );
    }

    // ---------- DNS 后端 ----------

    #[test]
    fn dns_resolvconf_receives_full_stdin_and_waits_on_exit_code() {
        let mut f = Fake::new().prog("resolvconf");
        let servers = vec!["8.8.8.8".to_string(), "114.114.114.114".to_string()];
        let r = apply_dns(&mut f, "eth1", &servers);
        assert!(r.is_ok(), "{:?}", r);

        assert_eq!(f.stdin_log.len(), 1, "resolvconf 应被调用一次并写入 stdin");
        let (cmd, body) = &f.stdin_log[0];
        assert_eq!(cmd, "resolvconf -a eth1", "应以真实接口名标识: {}", cmd);
        assert_eq!(
            body, "nameserver 8.8.8.8\nnameserver 114.114.114.114\n",
            "stdin 必须包含全部 nameserver（原代码未写 stdin）"
        );
    }

    #[test]
    fn dns_resolvconf_failure_propagates() {
        let mut f = Fake::new().prog("resolvconf");
        f.resolvconf
            .push_back(Out::fail_with("resolvconf: no such interface"));
        let r = apply_dns(&mut f, "eth1", &["8.8.8.8".to_string()]);
        assert!(r.is_err(), "resolvconf 非零退出必须传播");
    }

    #[test]
    fn dns_resolvectl_uses_real_ifname_and_all_servers_in_one_call() {
        let mut f = Fake::new().prog("resolvectl");
        let servers = vec!["8.8.8.8".to_string(), "114.114.114.114".to_string()];
        let r = apply_dns(&mut f, "eth1", &servers);
        assert!(r.is_ok(), "{:?}", r);

        let calls = f.calls_of("resolvectl");
        assert_eq!(
            calls,
            vec!["resolvectl dns eth1 8.8.8.8 114.114.114.114"],
            "应一次传全部 DNS 且用真实接口名: {:?}",
            calls
        );
        assert!(
            !calls[0].contains("bm_set_ip"),
            "不得再使用假的接口名: {}",
            calls[0]
        );
    }

    #[test]
    fn dns_resolvectl_failure_propagates() {
        let mut f = Fake::new().prog("resolvectl");
        f.resolvectl
            .push_back(Out::fail_with("Failed to set DNS configuration"));
        let r = apply_dns(&mut f, "eth1", &["8.8.8.8".to_string()]);
        assert!(r.is_err(), "resolvectl 失败必须传播");
    }

    #[test]
    fn dns_file_fallback_write_failure_propagates() {
        let mut f = Fake::new().file("/etc/resolv.conf", "nameserver 1.1.1.1\n");
        f.unwritable.insert("/etc/resolv.conf".into());
        let r = apply_dns(&mut f, "eth1", &["8.8.8.8".to_string()]);
        assert!(r.is_err(), "文件回退写失败必须传播（原代码只打印）");
    }

    #[test]
    fn dns_file_fallback_snapshots_and_writes_all_servers() {
        let mut f = Fake::new().file("/etc/resolv.conf", "nameserver 1.1.1.1\n");
        let servers = vec!["8.8.8.8".to_string(), "114.114.114.114".to_string()];
        let r = apply_dns(&mut f, "eth1", &servers);
        assert!(r.is_ok(), "{:?}", r);
        assert_eq!(
            f.files.get("/etc/resolv.conf").map(String::as_str),
            Some("nameserver 8.8.8.8\nnameserver 114.114.114.114\n")
        );
        assert_eq!(
            f.files
                .get("/etc/resolv.conf.bm_set_ip.bak")
                .map(String::as_str),
            Some("nameserver 1.1.1.1\n"),
            "应保留本次快照的备份"
        );
    }

    // ---------- 快照 / 回滚 ----------

    fn netplan_fake(original: &str, apply: Vec<Out>) -> Fake {
        let mut f = Fake::new()
            .prog("netplan")
            .file("/etc/netplan/01-netcfg.yaml", original)
            .file(
                // 陈旧遗留备份：绝不能用于回滚
                "/etc/netplan/01-netcfg.yaml.bm_set_ip.bak",
                "network:\n  version: 2\n  ethernets:\n    eth1:\n      addresses: [9.9.9.9/24]\n",
            );
        f.dirs.insert(
            "/etc/netplan".into(),
            vec![
                "01-netcfg.yaml".into(),
                "01-netcfg.yaml.bm_set_ip.bak".into(),
            ],
        );
        f.netplan_apply = apply.into();
        f
    }

    #[test]
    fn netplan_rollback_uses_this_run_snapshot_not_stale_bak() {
        // 原配置与陈旧 .bak 内容不同；apply 失败后必须恢复“原配置”而不是陈旧备份
        let original = "network:\n  version: 2\n  ethernets:\n    eth1:\n      mtu: 1400\n";
        let mut f = netplan_fake(
            original,
            vec![
                Out::fail_with("Error: Conflicting default route"),
                Out::ok_with(""),
            ],
        );
        let cfg = cfg_v4("eth1", &[("10.1.0.5", 24)], Some("10.1.0.1"), &[]);
        let r = configure_with_netplan(&cfg, &mut f);

        assert!(r.is_err(), "apply 失败必须非零");
        let restored = f
            .files
            .get("/etc/netplan/01-netcfg.yaml")
            .cloned()
            .unwrap_or_default();
        assert_eq!(restored, original, "必须恢复本次快照，而不是陈旧 .bak");
        assert!(
            !restored.contains("9.9.9.9"),
            "不得恢复陈旧备份内容: {}",
            restored
        );
        assert!(r.unwrap_err().contains("rolled back"), "应说明已回滚");
        assert!(
            !f.said().contains("applied successfully"),
            "失败不得输出成功文案"
        );
    }

    #[test]
    fn netplan_backup_failure_refuses_to_modify() {
        let original = "network:\n  version: 2\n  ethernets:\n    eth1:\n      mtu: 1400\n";
        let mut f = netplan_fake(original, vec![]);
        f.unwritable
            .insert("/etc/netplan/01-netcfg.yaml.bm_set_ip.bak".into());
        let cfg = cfg_v4("eth1", &[("10.1.0.5", 24)], None, &[]);
        let r = configure_with_netplan(&cfg, &mut f);

        assert!(r.is_err(), "备份失败必须拒绝修改");
        assert!(
            r.unwrap_err().contains("refusing to modify"),
            "错误应说明拒绝原因"
        );
        assert_eq!(
            f.files
                .get("/etc/netplan/01-netcfg.yaml")
                .map(String::as_str),
            Some(original),
            "原配置不得被改动"
        );
        assert!(
            f.calls_of("netplan apply").is_empty(),
            "拒绝时不得 apply: {:?}",
            f.calls
        );
    }

    #[test]
    fn netplan_unreadable_original_refuses_to_modify() {
        let mut f = netplan_fake("network: {}\n", vec![]);
        f.unreadable.insert("/etc/netplan/01-netcfg.yaml".into());
        let cfg = cfg_v4("eth1", &[("10.1.0.5", 24)], None, &[]);
        let r = configure_with_netplan(&cfg, &mut f);

        assert!(r.is_err(), "读不到原配置必须拒绝");
        assert!(f.calls_of("netplan apply").is_empty());
    }

    #[test]
    fn netplan_success_writes_and_applies() {
        let original = "network:\n  version: 2\n  ethernets: {}\n";
        let mut f = netplan_fake(original, vec![Out::ok_with("")]);
        let cfg = cfg_v4("eth1", &[("10.1.0.5", 24)], Some("10.1.0.1"), &["8.8.8.8"]);
        let r = configure_with_netplan(&cfg, &mut f);
        assert!(r.is_ok(), "{:?}", r);
        let written = f.files.get("/etc/netplan/01-netcfg.yaml").cloned().unwrap();
        assert!(written.contains("10.1.0.5/24"), "应写入地址: {}", written);
        assert_eq!(f.calls_of("netplan apply").len(), 1);
        assert!(f.said().contains("applied successfully"));
    }

    fn networkd_fake(file: Option<&str>, reconfigure: Vec<Out>) -> Fake {
        let mut f = Fake::new().prog("networkctl");
        if let Some(c) = file {
            f.files.insert(
                "/etc/systemd/network/10-eth1.network".to_string(),
                c.to_string(),
            );
        }
        f.netctl_reconfigure = reconfigure.into();
        f
    }

    #[test]
    fn networkd_removes_new_file_when_original_did_not_exist() {
        // 原文件不存在 + apply 失败 → 撤销本次新文件，而不是“恢复”出一个假的原文件
        let mut f = networkd_fake(
            None,
            vec![Out::fail_with("Failed to reconfigure"), Out::ok_with("")],
        );
        let cfg = cfg_v4("eth1", &[("10.1.0.5", 24)], None, &[]);
        let r = configure_with_networkd(&cfg, &mut f);

        assert!(r.is_err(), "reconfigure 失败必须非零");
        assert!(
            !f.exists("/etc/systemd/network/10-eth1.network"),
            "原文件不存在时失败必须撤销新文件: {:?}",
            f.files.keys().collect::<Vec<_>>()
        );
        assert!(
            !f.exists("/etc/systemd/network/10-eth1.network.bm_set_ip.bak"),
            "原本没有文件时不应凭空产生 .bak"
        );
    }

    #[test]
    fn networkd_restores_existing_file_on_apply_failure() {
        let original = "[Match]\nName=eth1\n\n[Network]\nDHCP=ipv4\n";
        let mut f = networkd_fake(
            Some(original),
            vec![Out::fail_with("Failed to reconfigure"), Out::ok_with("")],
        );
        let cfg = cfg_v4("eth1", &[("10.1.0.5", 24)], None, &[]);
        let r = configure_with_networkd(&cfg, &mut f);

        assert!(r.is_err());
        assert_eq!(
            f.files
                .get("/etc/systemd/network/10-eth1.network")
                .map(String::as_str),
            Some(original),
            "必须恢复原文件"
        );
    }

    #[test]
    fn networkd_missing_original_and_success_leaves_new_file() {
        let mut f = networkd_fake(None, vec![Out::ok_with("")]);
        let cfg = cfg_v4("eth1", &[("10.1.0.5", 24)], None, &[]);
        let r = configure_with_networkd(&cfg, &mut f);
        assert!(r.is_ok(), "{:?}", r);
        let written = f
            .files
            .get("/etc/systemd/network/10-eth1.network")
            .cloned()
            .unwrap();
        assert!(written.contains("Address=10.1.0.5/24"), "{}", written);
    }
}
