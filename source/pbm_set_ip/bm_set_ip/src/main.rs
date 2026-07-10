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

/// 路由策略(单,from/to 可选)
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
    policy: Option<Policy>,
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
        let prefix = nm.as_deref().map(|m| m.parse::<u8>().unwrap_or(128)).unwrap_or(128);
        let v6f = Family {
            addrs: vec![(addr1, prefix)],
            gateway: gw,
            dns,
            is_dhcp: false,
        };
        (None, Some(v6f))
    } else {
        let is_dhcp4 = is_dhcp_token(&addr1);
        let prefix = nm.as_deref().map(mask_to_prefix).unwrap_or(32);
        let v4f = Family {
            addrs: if is_dhcp4 { vec![] } else { vec![(addr1, prefix)] },
            gateway: gw,
            dns,
            is_dhcp: is_dhcp4,
        };
        let v6f = ipv6.as_ref().map(|_| {
            let is_dhcp6 = ipv6.as_deref().map(is_dhcp_token).unwrap_or(false);
            let prefix = ipv6_prefix.as_deref().map(|m| m.parse::<u8>().unwrap_or(128)).unwrap_or(128);
            Family {
                addrs: if is_dhcp6 {
                    vec![]
                } else {
                    ipv6.as_ref().map(|a| vec![(a.clone(), prefix)]).unwrap_or_default()
                },
                gateway: ipv6_gateway,
                dns: ipv6_dns,
                is_dhcp: is_dhcp6,
            }
        });
        (Some(v4f), v6f)
    };

    Ok(Some(Config {
        net_device: net_device.to_string(),
        family1_is_v6,
        v4,
        v6,
        routes: Vec::new(),
        policy: None,
        dry_run: false,
    }))
}

// ============ 4 元组模式(IP+其它)============

fn parse_4tuple(net_device: &str, rest: &[String]) -> Result<Config, lexopt::Error> {
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
        let (prefix, gw, dns) = read_3slots(rest, &mut i);
        let p = prefix.as_deref().map(|m| m.parse::<u8>().unwrap_or(128)).unwrap_or(128);
        v6 = Some(Family { addrs: vec![(addr1, p)], gateway: gw, dns, is_dhcp: false });
    } else if family1_is_dhcp {
        // dhcp 单 token
        v4 = Some(Family { addrs: vec![], gateway: None, dns: None, is_dhcp: true });
    } else {
        // v4 static family1:4 元组(addr1 已消费,读 mask/gw/dns)
        let (mask, gw, dns) = read_3slots(rest, &mut i);
        let p = mask.as_deref().map(mask_to_prefix).unwrap_or(32);
        v4 = Some(Family { addrs: vec![(addr1, p)], gateway: gw, dns, is_dhcp: false });
    }

    let mut routes: Vec<Route> = Vec::new();
    let mut policy: Option<Policy> = None;

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
                let (prefix, gw, dns) = read_3slots(rest, &mut i);
                let p = prefix.as_deref().map(|m| m.parse::<u8>().unwrap_or(128)).unwrap_or(128);
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

        if g2.is_empty() {
            // 额外地址:addr mask '' ''
            if !g3.is_empty() {
                return Err("extra address group must be 'addr mask '' ''".into());
            }
            let p = mask_to_prefix(&g1);
            if family1_is_v6 {
                let p = if g1.parse::<u8>().is_ok() { g1.parse::<u8>().unwrap() } else { p };
                v6.as_mut().unwrap().addrs.push((g0, p));
            } else {
                v4.as_mut().unwrap().addrs.push((g0, p));
            }
            i += 4;
        } else if is_dotted_quad(&g3) {
            // 策略(单):from from_mask to to_mask
            if policy.is_some() {
                return Err("only one policy group allowed".into());
            }
            let from = (g0, mask_to_prefix(&g1));
            let to = (g2, mask_to_prefix(&g3));
            policy = Some(Policy { from: Some(from), to: Some(to), table: None });
            i += 4;
        } else if g3.is_empty() || g3.parse::<u32>().is_ok() || is_table_name(&g3) {
            // 路由:to to_mask via table
            routes.push(Route {
                to: g0,
                to_prefix: mask_to_prefix(&g1),
                via: Some(g2),
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

    // 策略 table 取最后一条路由的 table
    if let Some(p) = policy.as_mut() {
        p.table = routes.last().and_then(|r| r.table.clone());
        if p.table.is_none() {
            return Err("policy requires a preceding route (for table)".into());
        }
    }

    Ok(Config {
        net_device: net_device.to_string(),
        family1_is_v6,
        v4,
        v6,
        routes,
        policy,
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
        && s.chars().all(|c| c.is_alphanumeric() || c == '_')
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

// ============ 掩码转换 ============

fn mask_to_prefix(mask: &str) -> u8 {
    if let Ok(prefix) = mask.parse::<u8>() {
        if prefix <= 32 {
            return prefix;
        }
    }
    mask.split('.')
        .map(|s| s.parse::<u8>().unwrap_or(0))
        .map(|b| b.count_ones())
        .sum::<u32>() as u8
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
            eprintln!("  Route+policy(4-tuple):     bm_set_ip eth0 192.168.1.100 24 '' ''  192.168.2.0 24 192.168.1.1 100  10.0.0.0 24 192.168.3.0 255.255.255.0");
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

    match &cfg.policy {
        Some(p) => {
            println!("policy.present=true");
            if let Some((n, px)) = &p.from {
                println!("policy.from={}", n);
                println!("policy.from_prefix={}", px);
            } else {
                println!("policy.from=");
                println!("policy.from_prefix=");
            }
            if let Some((n, px)) = &p.to {
                println!("policy.to={}", n);
                println!("policy.to_prefix={}", px);
            } else {
                println!("policy.to=");
                println!("policy.to_prefix=");
            }
            println!("policy.table={}", p.table.as_deref().unwrap_or(""));
        }
        None => {
            println!("policy.present=false");
            println!("policy.from=");
            println!("policy.from_prefix=");
            println!("policy.to=");
            println!("policy.to_prefix=");
            println!("policy.table=");
        }
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
    if is_command_exists("netplan") {
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

    // 策略
    if let Some(p) = &cfg.policy {
        let mut policy_seq: Vec<Value> = Vec::new();
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

    let status = Command::new("netplan").arg("apply").status();
    if let Ok(s) = status {
        if s.success() {
            println!("[INFO] Netplan configuration applied successfully");
        } else {
            eprintln!("[ERROR] Failed to apply netplan configuration");
        }
    } else {
        eprintln!("[ERROR] Could not run netplan");
    }
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
    // 静态路由
    if !cfg.routes.is_empty() {
        let entries: Vec<String> = cfg.routes.iter().map(|r| {
            let mut e = format!("{}/{}", r.to, r.to_prefix);
            if let Some(via) = &r.via { e.push_str(&format!(" {}", via)); }
            if let Some(t) = &r.table { e.push_str(&format!(" {}", t)); }
            e
        }).collect();
        add_args.push("ipv4.routes".into());
        add_args.push(entries.join(","));
    }
    // 策略
    if let Some(p) = &cfg.policy {
        if let Some(t) = &p.table {
            let mut rules: Vec<String> = Vec::new();
            if let Some((n, px)) = &p.from {
                rules.push(format!("from {}/{} table {}", n, px, t));
            }
            if let Some((n, px)) = &p.to {
                rules.push(format!("to {}/{} table {}", n, px, t));
            }
            if !rules.is_empty() {
                add_args.push("ipv4.routing-rules".into());
                add_args.push(rules.join(", "));
            }
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
    if let Some(p) = &cfg.policy {
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
    let status = Command::new("systemctl").args(["restart", "systemd-networkd"]).status();
    if let Ok(s) = status {
        if s.success() {
            println!("[INFO] systemd-networkd configuration applied successfully");
        } else {
            eprintln!("[ERROR] Failed to restart systemd-networkd");
        }
    } else {
        eprintln!("[ERROR] Could not run systemctl");
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

    let _ = Command::new("ip").args(["addr", "flush", "dev", &cfg.net_device]).status();

    if let Some(v4f) = &cfg.v4 {
        for (a, p) in &v4f.addrs {
            let _ = Command::new("ip").args(["addr", "add", &format!("{}/{}", a, p), "dev", &cfg.net_device]).status();
        }
        if let Some(gw) = &v4f.gateway {
            if !gw.is_empty() {
                let _ = Command::new("ip").args(["route", "add", "default", "via", gw, "dev", &cfg.net_device]).status();
            }
        }
    }
    if let Some(v6f) = &cfg.v6 {
        for (a, p) in &v6f.addrs {
            let _ = Command::new("ip").args(["addr", "add", &format!("{}/{}", a, p), "dev", &cfg.net_device]).status();
        }
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
        let _ = Command::new("ip").args(&args).status();
    }
    if let Some(p) = &cfg.policy {
        if let Some(t) = &p.table {
            if let Some((n, px)) = &p.from {
                let _ = Command::new("ip").args(["rule", "add", "from", &format!("{}/{}", n, px), "table", t]).status();
            }
            if let Some((n, px)) = &p.to {
                let _ = Command::new("ip").args(["rule", "add", "to", &format!("{}/{}", n, px), "table", t]).status();
            }
        }
    }

    let status = Command::new("ip").args(["link", "set", "dev", &cfg.net_device, "up"]).status();
    if let Ok(s) = status {
        if s.success() {
            println!("[INFO] Manual IP configuration applied successfully");
        } else {
            eprintln!("[ERROR] Failed to bring up the interface");
        }
    } else {
        eprintln!("[ERROR] Could not run ip command to bring up interface");
    }
}
