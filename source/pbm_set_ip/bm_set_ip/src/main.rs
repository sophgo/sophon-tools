use lexopt;
use serde_yaml;
use serde_yaml::{Mapping, Value};
use std::env;
use std::fs;
use std::io::Write;
use std::process::exit;
use std::process::Command;

/// 命令行参数(组模式匹配解析)
///
/// 组顺序(family1 → 路由 → 策略 → family2):
///   f1: addr1 mask1 gateway dns            # IP 配置组1
///   rt: to to_mask via table               # IPv4 静态路由
///   pl: rule_from rule_from_mask rule_to rule_to_mask   # IPv4 路由策略
///   f2: addr2 mask2 gateway dns            # IP 配置组2(IPv6)
///
/// family1 由 addr1 形状决定 v4/v6/dhcp;family2 仅在 family1 为 v4 时出现。
/// 详见 cmd_note.md 与 docs/superpowers/specs/2026-07-10-bm_set_ip-routes-policy-design.md。
#[derive(Default)]
struct Args {
    net_device: String,
    /// IPv4 地址 / dhcp / (family1_is_v6 时为 IPv6 地址)
    ip: Option<String>,
    /// IPv4 掩码 / 前缀(family1_is_v6 时为 IPv6 前缀)
    netmask: Option<String>,
    /// IPv4 网关(family1_is_v6 时为 IPv6 网关)
    gateway: Option<String>,
    /// IPv4 DNS(family1_is_v6 时为 IPv6 DNS)
    dns: Option<String>,
    // IPv4 静态路由
    to: Option<String>,
    to_mask: Option<String>,
    via: Option<String>,
    table: Option<String>,
    // IPv4 路由策略
    rule_from: Option<String>,
    rule_from_mask: Option<String>,
    rule_to: Option<String>,
    rule_to_mask: Option<String>,
    // family2(IPv6,仅 family1 为 v4 时)
    ipv6: Option<String>,
    ipv6_prefix: Option<String>,
    ipv6_gateway: Option<String>,
    ipv6_dns: Option<String>,

    /// family1 是否为 IPv6(模式2:仅 IPv6)
    family1_is_v6: bool,

    /// 无实施模式:仅解析 + 打印分析配置,不应用、不需 root
    dry_run: bool,
}

impl Args {
    fn parse() -> Result<Self, lexopt::Error> {
        use lexopt::prelude::*;

        let mut positional: Vec<String> = Vec::new();
        let mut dry_run = false;
        let mut parser = lexopt::Parser::from_env();
        while let Some(arg) = parser.next()? {
            match arg.clone() {
                Value(val) => positional.push(val.into_string()?),
                Long(name) if name == "dry-run" => {
                    dry_run = true;
                }
                Short('n') => {
                    dry_run = true;
                }
                _ => return Err(arg.unexpected()),
            }
        }

        if positional.is_empty() {
            return Err("missing required argument: net_device".into());
        }
        let net_device = positional[0].clone();
        let rest: Vec<String> = positional[1..].to_vec();
        let mut i = 0usize;

        let mut a = Args::default();
        a.net_device = net_device;
        a.dry_run = dry_run;

        // ---- family1: addr1 必填 ----
        let addr1 = match rest.get(i) {
            Some(v) if !v.is_empty() => {
                i += 1;
                v.clone()
            }
            _ => return Err("missing required argument: ip".into()),
        };
        a.ip = Some(addr1.clone());
        a.family1_is_v6 = looks_like_ipv6(&addr1);
        let family1_is_v4 = !a.family1_is_v6; // 含 v4 静态与 v4-dhcp(addr1=dhcp 无冒号 → v4)

        // family1 可选槽:netmask / gateway / dns
        // 形状门:family1 为 v4 时,遇到 IPv6/dhcp token → 跳转到 family2
        let (nm, gw, dns, jumped_to_f2) = fill_family1_optional(&rest, &mut i, family1_is_v4);
        a.netmask = nm;
        a.gateway = gw;
        a.dns = dns;

        if !jumped_to_f2 {
            // 路由 + 策略(仅 IPv4),形状门可跳 family2
            let (slots, jumped2) = fill_routes_policy(&rest, &mut i, family1_is_v4);
            a.to = slots.get(0).cloned().flatten();
            a.to_mask = slots.get(1).cloned().flatten();
            a.via = slots.get(2).cloned().flatten();
            a.table = slots.get(3).cloned().flatten();
            a.rule_from = slots.get(4).cloned().flatten();
            a.rule_from_mask = slots.get(5).cloned().flatten();
            a.rule_to = slots.get(6).cloned().flatten();
            a.rule_to_mask = slots.get(7).cloned().flatten();
            if jumped2 {
                fill_family2(&rest, &mut i, &mut a);
            }
        } else {
            // family1 直接跳到 family2
            fill_family2(&rest, &mut i, &mut a);
        }

        // 异常输入:未消费的非空 trailing token(告警,不中断)
        let mut leftover = 0;
        while i < rest.len() {
            if !rest[i].is_empty() {
                leftover += 1;
            }
            i += 1;
        }
        if leftover > 0 {
            eprintln!("[WARNING] {} unexpected trailing argument(s) ignored", leftover);
        }

        Ok(a)
    }
}

/// token 是否为 IPv6 格式(含冒号)
fn looks_like_ipv6(s: &str) -> bool {
    s.contains(':')
}

/// token 是否为 dhcp/auto
fn is_dhcp_token(s: &str) -> bool {
    let l = s.to_lowercase();
    l == "dhcp" || l == "auto"
}

/// 取一个 token 是否触发"跳转 family2"(IPv6 形状或 dhcp/auto)
fn jumps_to_family2(t: &str) -> bool {
    looks_like_ipv6(t) || is_dhcp_token(t)
}

/// 填充 family1 的可选槽(netmask/gateway/dns)
/// 返回 (netmask, gateway, dns, jumped_to_f2)
fn fill_family1_optional(
    rest: &[String],
    i: &mut usize,
    family1_is_v4: bool,
) -> (Option<String>, Option<String>, Option<String>, bool) {
    let mut slots: [Option<String>; 3] = [None, None, None];
    for idx in 0..3 {
        match rest.get(*i) {
            None => break, // 尾部
            Some(v) if v.is_empty() => {
                *i += 1; // 占位符
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

/// 填充路由+策略 8 槽(to/to_mask/via/table/rule_from/rule_from_mask/rule_to/rule_to_mask)
/// 返回 (8 元素 Vec<Option<String>>, jumped_to_f2)
fn fill_routes_policy(rest: &[String], i: &mut usize, family1_is_v4: bool) -> (Vec<Option<String>>, bool) {
    let mut out: Vec<Option<String>> = Vec::with_capacity(8);
    for _ in 0..8 {
        match rest.get(*i) {
            None => {
                out.push(None); // 尾部:剩余补 None
            }
            Some(v) if v.is_empty() => {
                *i += 1;
                out.push(None);
            }
            Some(v) => {
                if family1_is_v4 && jumps_to_family2(v) {
                    return (out, true);
                }
                out.push(Some(v.clone()));
                *i += 1;
            }
        }
    }
    // 8 槽填满后,若紧跟 IPv6/dhcp token → 跳转 family2
    if let Some(v) = rest.get(*i) {
        if family1_is_v4 && jumps_to_family2(v) {
            return (out, true);
        }
    }
    (out, false)
}

/// 填充 family2(IPv6)4 槽:addr2/prefix/gateway/dns。无形状门(其后无内容)。
fn fill_family2(rest: &[String], i: &mut usize, a: &mut Args) {
    let mut idx = *i;
    let mut slots: [&mut Option<String>; 4] = [
        &mut a.ipv6,
        &mut a.ipv6_prefix,
        &mut a.ipv6_gateway,
        &mut a.ipv6_dns,
    ];
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

#[derive(Debug)]
enum NetManager {
    Netplan,
    NetworkManager,
    SystemdNetworkd,
    Unknown,
}

/// 一个地址族配置(v4 或 v6)
struct IpFamily {
    addr: Option<String>,
    netmask: Option<String>,
    gateway: Option<String>,
    dns: Option<String>,
    is_dhcp: bool,
}

/// 路由 + 路由策略(仅 IPv4),掩码已转前缀,table 已归一
struct RoutesPolicy {
    to: Option<String>,
    to_prefix: Option<String>,
    via: Option<String>,
    table: Option<String>,
    rule_from: Option<String>,
    rule_from_prefix: Option<String>,
    rule_to: Option<String>,
    rule_to_prefix: Option<String>,
}

fn main() {
    let args = match Args::parse() {
        Ok(args) => args,
        Err(e) => {
            eprintln!("Error: {}", e);
            eprintln!(
                "\nUsage: {} [--dry-run|-n] <net_device> <ip|dhcp> <netmask> [gateway] [dns] [to] [to_mask] [via] [table] [rule_from] [rule_from_mask] [rule_to] [rule_to_mask] [ipv6|dhcp] [ipv6_prefix] [ipv6_gateway] [ipv6_dns]",
                env::args().next().unwrap_or("bm_set_ip".into())
            );
            eprintln!("\nExamples:");
            eprintln!("  DHCP IPv4:            bm_set_ip eth0 dhcp ''");
            eprintln!("  DHCP IPv4+IPv6:      bm_set_ip eth0 dhcp '' '' '' dhcp");
            eprintln!("  Static IPv4:         bm_set_ip eth0 192.168.1.100 24 192.168.1.1");
            eprintln!("  Static IPv6(新):     bm_set_ip eth0 2001:db8::1 64 fe80::1");
            eprintln!("  Static IPv4+IPv6:    bm_set_ip eth0 192.168.1.100 24 192.168.1.1 8.8.8.8 2001:db8::1 64 fe80::1");
            eprintln!("  IPv4 + 静态路由:     bm_set_ip eth0 192.168.1.100 24 '' '' 192.168.2.0 24 192.168.1.1 100");
            eprintln!("  IPv4 + 路由+策略:    bm_set_ip eth0 192.168.1.100 24 192.168.1.1 8.8.8.8 192.168.2.0 24 192.168.1.1 100 10.0.0.0 24 192.168.3.0 24");
            eprintln!("  Dry-run(只解析不应用): bm_set_ip --dry-run eth0 192.168.1.100 24 192.168.1.1 8.8.8.8 192.168.2.0 24 192.168.1.1 100");
            exit(1);
        }
    };

    // 构造 v4 / v6 地址族 + 路由策略(纯解析,无副作用)
    let (v4, v6) = build_families(&args);
    let rp = build_routes_policy(&args);

    // 无实施模式:仅打印分析配置,不应用、不需 root
    if args.dry_run {
        print_analyzed_config(&args.net_device, &v4, &v6, &rp, args.family1_is_v6);
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

    // 校验:v4 静态必须有掩码
    if let Some(v4) = &v4 {
        if !v4.is_dhcp && v4.addr.is_some() && v4.netmask.is_none() {
            eprintln!("[ERROR] IPv4 static address requires a netmask");
            exit(1);
        }
    }

    let net_manager = detect_net_manager();
    match net_manager {
        NetManager::Netplan => {
            println!("[INFO] Using netplan for network configuration");
            configure_with_netplan(&args, &v4, &v6, &rp);
        }
        NetManager::NetworkManager => {
            println!("[INFO] Using NetworkManager (nmcli) for network configuration");
            configure_with_nmcli(&args, &v4, &v6, &rp);
        }
        NetManager::SystemdNetworkd => {
            println!("[INFO] Using systemd-networkd for network configuration");
            configure_with_networkd(&args, &v4, &v6, &rp);
        }
        NetManager::Unknown => {
            eprintln!("[ERROR] Could not detect a supported network manager!");
            eprintln!("[INFO] Trying to configure IP manually using ip command");
            configure_with_ip(&args, &v4, &v6, &rp);
        }
    }
}

/// 由 Args 构造 (v4, v6) 地址族
fn build_families(a: &Args) -> (Option<IpFamily>, Option<IpFamily>) {
    if a.family1_is_v6 {
        // 模式2:family1 即 IPv6,无 v4,无 family2
        let v6 = IpFamily {
            addr: a.ip.clone(),
            netmask: a.netmask.clone(),
            gateway: a.gateway.clone(),
            dns: a.dns.clone(),
            is_dhcp: false, // addr1 含冒号,非 dhcp
        };
        (None, Some(v6))
    } else {
        // family1 为 v4(静态或 dhcp)
        let is_dhcp4 = a.ip.as_deref().map(is_dhcp_token).unwrap_or(false);
        let v4 = IpFamily {
            addr: a.ip.clone(),
            netmask: a.netmask.clone(),
            gateway: a.gateway.clone(),
            dns: a.dns.clone(),
            is_dhcp: is_dhcp4,
        };
        let v6 = if a.ipv6.is_some() {
            let is_dhcp6 = a.ipv6.as_deref().map(is_dhcp_token).unwrap_or(false);
            Some(IpFamily {
                addr: a.ipv6.clone(),
                netmask: a.ipv6_prefix.clone(),
                gateway: a.ipv6_gateway.clone(),
                dns: a.ipv6_dns.clone(),
                is_dhcp: is_dhcp6,
            })
        } else {
            None
        };
        (Some(v4), v6)
    }
}

/// 由 Args 构造路由策略(掩码→前缀,table 归一)
fn build_routes_policy(a: &Args) -> RoutesPolicy {
    let norm = |s: &Option<String>| -> Option<String> {
        s.as_deref().filter(|s| !s.is_empty()).map(|s| s.to_string())
    };
    let to_prefix = a.to_mask.as_ref().and_then(|m| {
        if m.is_empty() {
            None
        } else {
            Some(mask_to_prefix(m).to_string())
        }
    });
    let rule_from_prefix = a.rule_from_mask.as_ref().and_then(|m| {
        if m.is_empty() {
            None
        } else {
            Some(mask_to_prefix(m).to_string())
        }
    });
    let rule_to_prefix = a.rule_to_mask.as_ref().and_then(|m| {
        if m.is_empty() {
            None
        } else {
            Some(mask_to_prefix(m).to_string())
        }
    });
    RoutesPolicy {
        to: norm(&a.to),
        to_prefix,
        via: norm(&a.via),
        table: norm(&a.table),
        rule_from: norm(&a.rule_from),
        rule_from_prefix,
        rule_to: norm(&a.rule_to),
        rule_to_prefix,
    }
}

/// 无实施模式:按固定格式打印解析出的配置,供自动化测试断言。
/// 格式为 `key=value` 行,缺失字段输出空值;首尾用 `## begin` / `## end` 包围以便截取。
fn print_analyzed_config(
    net_device: &str,
    v4: &Option<IpFamily>,
    v6: &Option<IpFamily>,
    rp: &RoutesPolicy,
    family1_is_v6: bool,
) {
    println!("## bm_set_ip dry-run config begin");
    println!("net_device={}", net_device);
    println!("family1_is_v6={}", family1_is_v6);

    // IPv4 族
    match v4 {
        Some(f) => {
            println!("v4.present=true");
            println!("v4.addr={}", f.addr.as_deref().unwrap_or(""));
            println!("v4.netmask={}", f.netmask.as_deref().unwrap_or(""));
            println!("v4.gateway={}", f.gateway.as_deref().unwrap_or(""));
            println!("v4.dns={}", f.dns.as_deref().unwrap_or(""));
            println!("v4.is_dhcp={}", f.is_dhcp);
        }
        None => {
            println!("v4.present=false");
            println!("v4.addr=");
            println!("v4.netmask=");
            println!("v4.gateway=");
            println!("v4.dns=");
            println!("v4.is_dhcp=false");
        }
    }

    // IPv6 族(netmask 字段对 v6 持有前缀)
    match v6 {
        Some(f) => {
            println!("v6.present=true");
            println!("v6.addr={}", f.addr.as_deref().unwrap_or(""));
            println!("v6.prefix={}", f.netmask.as_deref().unwrap_or(""));
            println!("v6.gateway={}", f.gateway.as_deref().unwrap_or(""));
            println!("v6.dns={}", f.dns.as_deref().unwrap_or(""));
            println!("v6.is_dhcp={}", f.is_dhcp);
        }
        None => {
            println!("v6.present=false");
            println!("v6.addr=");
            println!("v6.prefix=");
            println!("v6.gateway=");
            println!("v6.dns=");
            println!("v6.is_dhcp=false");
        }
    }

    // IPv4 静态路由(掩码已转前缀)
    println!("routes.to={}", rp.to.as_deref().unwrap_or(""));
    println!("routes.to_prefix={}", rp.to_prefix.as_deref().unwrap_or(""));
    println!("routes.via={}", rp.via.as_deref().unwrap_or(""));
    println!("routes.table={}", rp.table.as_deref().unwrap_or(""));

    // IPv4 路由策略(掩码已转前缀)
    println!("policy.rule_from={}", rp.rule_from.as_deref().unwrap_or(""));
    println!(
        "policy.rule_from_prefix={}",
        rp.rule_from_prefix.as_deref().unwrap_or("")
    );
    println!("policy.rule_to={}", rp.rule_to.as_deref().unwrap_or(""));
    println!(
        "policy.rule_to_prefix={}",
        rp.rule_to_prefix.as_deref().unwrap_or("")
    );
    println!("## bm_set_ip dry-run config end");
}

/// 检测命令
fn is_command_exists(cmd: &str) -> bool {
    if let Some(paths) = std::env::var_os("PATH") {
        for path in std::env::split_paths(&paths) {
            let full_path = path.join(cmd);
            if full_path.is_file() {
                return true;
            }
        }
    }
    false
}

/// 掩码字符串/前缀数字 → 前缀数字
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

/// 返回所有非本设备的默认路由行
fn extra_default_routes(current_dev: &str) -> Vec<String> {
    let mut others = Vec::new();
    if let Ok(output) = Command::new("ip")
        .args(["route", "show", "default"])
        .output()
    {
        let routes = String::from_utf8_lossy(&output.stdout);
        for line in routes.lines() {
            if line.starts_with("default ") && !line.contains(&format!("dev {}", current_dev)) {
                others.push(line.to_string());
            }
        }
    }
    others
}

/// 检测网络管理方式
fn detect_net_manager() -> NetManager {
    if is_command_exists("netplan") {
        return NetManager::Netplan;
    }
    if is_command_exists("nmcli") {
        let status = Command::new("systemctl")
            .arg("is-active")
            .arg("NetworkManager")
            .output();
        if let Ok(output) = status {
            if output.stdout == b"active\n" {
                return NetManager::NetworkManager;
            }
        }
    }
    let status = Command::new("systemctl")
        .arg("is-active")
        .arg("systemd-networkd")
        .output();
    if let Ok(output) = status {
        if output.stdout == b"active\n" {
            return NetManager::SystemdNetworkd;
        }
    }
    NetManager::Unknown
}

/// 判断是否是 root 权限
fn is_root() -> bool {
    unsafe { libc::geteuid() == 0 }
}

/// 获取 netplan 配置中的子 mapping(不存在则创建)
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

/// 配置 netplan
fn configure_with_netplan(args: &Args, v4: &Option<IpFamily>, v6: &Option<IpFamily>, rp: &RoutesPolicy) {
    let file_path = "/etc/netplan/01-netcfg.yaml";
    if fs::File::open(file_path).is_err() {
        eprintln!("[ERROR] Cannot read {}", file_path);
        std::process::exit(1);
    }
    let content =
        fs::read_to_string(file_path).expect("[ERROR] Error: Cannot read netplan config file");
    let mut doc: serde_yaml::Value = match serde_yaml::from_str(&content) {
        Ok(doc) => doc,
        Err(e) => {
            eprintln!(
                "[ERROR] YAML parsing failed: {}\nError location: {:?}",
                e,
                e.location()
            );
            panic!("[ERROR] YAML parsing aborted");
        }
    };

    let network_map = doc.as_mapping_mut().unwrap();
    let ethernets_map = get_or_create_mapping(network_map, "network");
    let ethernets = get_or_create_mapping(ethernets_map, "ethernets");

    let dev = args.net_device.clone();
    let mut dev_cfg = serde_yaml::Mapping::new();
    let mut addresses_seq: Vec<Value> = Vec::new();
    let mut routes_seq: Vec<Value> = Vec::new();

    // ---- IPv4 family ----
    if let Some(v4f) = v4 {
        if v4f.is_dhcp {
            let extra_routes = extra_default_routes(&args.net_device);
            if !extra_routes.is_empty() {
                eprintln!("[WARNING] system has extra default routes on other devices:");
                for r in &extra_routes {
                    eprintln!("[WARNING]     {}", r);
                }
            }
            dev_cfg.insert(Value::String("dhcp4".into()), Value::Bool(true));
        } else if let Some(addr) = &v4f.addr {
            let prefix = v4f
                .netmask
                .as_deref()
                .map(mask_to_prefix)
                .unwrap_or(32);
            dev_cfg.insert(Value::String("dhcp4".into()), Value::Bool(false));
            addresses_seq.push(Value::String(format!("{}/{}", addr, prefix)));
            // 默认网关 → routes(to:0.0.0.0/0, via:gw),替代已废弃的 gateway4
            if let Some(gw) = &v4f.gateway {
                if !gw.is_empty() {
                    let extra_routes = extra_default_routes(&args.net_device);
                    if !extra_routes.is_empty() {
                        eprintln!("[WARNING] system has extra default routes on other devices:");
                        for r in &extra_routes {
                            eprintln!("[WARNING]     {}", r);
                        }
                    }
                    let mut r = Mapping::new();
                    r.insert(Value::String("to".into()), Value::String("0.0.0.0/0".into()));
                    r.insert(Value::String("via".into()), Value::String(gw.clone()));
                    routes_seq.push(Value::Mapping(r));
                }
            }
        }
    }

    // ---- IPv4 静态路由(to/via/table)----
    if let (Some(to), Some(prefix)) = (&rp.to, &rp.to_prefix) {
        let mut r = Mapping::new();
        r.insert(
            Value::String("to".into()),
            Value::String(format!("{}/{}", to, prefix)),
        );
        if let Some(via) = &rp.via {
            r.insert(Value::String("via".into()), Value::String(via.clone()));
        }
        if let Some(t) = &rp.table {
            r.insert(Value::String("table".into()), Value::String(t.clone()));
        }
        routes_seq.push(Value::Mapping(r));
    }

    // ---- IPv6 family ----
    if let Some(v6f) = v6 {
        if v6f.is_dhcp {
            dev_cfg.insert(Value::String("dhcp6".into()), Value::Bool(true));
        } else if let Some(addr) = &v6f.addr {
            let prefix = v6f
                .netmask
                .as_deref()
                .map(|m| m.parse::<u8>().unwrap_or(128))
                .unwrap_or(128);
            dev_cfg.insert(Value::String("dhcp6".into()), Value::Bool(false));
            addresses_seq.push(Value::String(format!("{}/{}", addr, prefix)));
            // 默认网关 → routes(to:::/0, via:gw),替代已废弃的 gateway6
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

    if !addresses_seq.is_empty() {
        dev_cfg.insert(
            Value::String("addresses".into()),
            Value::Sequence(addresses_seq),
        );
    }
    if !routes_seq.is_empty() {
        dev_cfg.insert(Value::String("routes".into()), Value::Sequence(routes_seq));
    }

    // ---- IPv4 路由策略(routing-policy)----
    let mut policy_seq: Vec<Value> = Vec::new();
    if let Some(rf) = &rp.rule_from {
        let mut p = Mapping::new();
        let from_str = match &rp.rule_from_prefix {
            Some(px) => format!("{}/{}", rf, px),
            None => rf.clone(),
        };
        p.insert(Value::String("from".into()), Value::String(from_str));
        if let Some(t) = &rp.table {
            p.insert(Value::String("table".into()), Value::String(t.clone()));
        }
        policy_seq.push(Value::Mapping(p));
    }
    if let Some(rt) = &rp.rule_to {
        let mut p = Mapping::new();
        let to_str = match &rp.rule_to_prefix {
            Some(px) => format!("{}/{}", rt, px),
            None => rt.clone(),
        };
        p.insert(Value::String("to".into()), Value::String(to_str));
        if let Some(t) = &rp.table {
            p.insert(Value::String("table".into()), Value::String(t.clone()));
        }
        policy_seq.push(Value::Mapping(p));
    }
    if !policy_seq.is_empty() {
        if rp.table.is_none() {
            eprintln!("[WARNING] routing-policy without a table is meaningless; entries will not direct to a routing table");
        }
        dev_cfg.insert(
            Value::String("routing-policy".into()),
            Value::Sequence(policy_seq),
        );
    }

    // ---- DNS(v4 + v6 合并)----
    let mut dns_list = Vec::new();
    if let Some(v4f) = v4 {
        if let Some(d) = &v4f.dns {
            if !d.is_empty() {
                dns_list.push(Value::String(d.clone()));
            }
        }
    }
    if let Some(v6f) = v6 {
        if let Some(d) = &v6f.dns {
            if !d.is_empty() {
                dns_list.push(Value::String(d.clone()));
            }
        }
    }
    if !dns_list.is_empty() {
        let mut dns_map = serde_yaml::Mapping::new();
        dns_map.insert(
            Value::String("addresses".into()),
            Value::Sequence(dns_list),
        );
        dev_cfg.insert(
            Value::String("nameservers".into()),
            Value::Mapping(dns_map),
        );
    }

    dev_cfg.insert(Value::String("optional".into()), Value::Bool(true));
    println!("[INFO] Add config: {:?}", dev_cfg);

    ethernets.insert(
        Value::String(dev),
        Value::Mapping(dev_cfg),
    );

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

/// 配置 nmcli
fn configure_with_nmcli(args: &Args, v4: &Option<IpFamily>, v6: &Option<IpFamily>, rp: &RoutesPolicy) {
    let con_name = format!("static-{}", &args.net_device);

    let _ = Command::new("nmcli")
        .args(["con", "delete", &con_name])
        .output();

    let mut add_args: Vec<String> = vec![
        "con".into(),
        "add".into(),
        "type".into(),
        "ethernet".into(),
        "ifname".into(),
        args.net_device.clone().into(),
        "con-name".into(),
        con_name.clone().into(),
        "connection.autoconnect-priority".into(),
        "10".into(),
    ];

    // IPv4
    if let Some(v4f) = v4 {
        if v4f.is_dhcp {
            let extra_routes = extra_default_routes(&args.net_device);
            if !extra_routes.is_empty() {
                eprintln!("[WARNING] system has extra default routes on other devices:");
                for r in &extra_routes {
                    eprintln!("[WARNING]     {}", r);
                }
            }
            add_args.push("ipv4.method".into());
            add_args.push("auto".into());
        } else if let Some(addr) = &v4f.addr {
            let prefix = v4f.netmask.as_deref().map(mask_to_prefix).unwrap_or(32);
            add_args.push("ipv4.addresses".into());
            add_args.push(format!("{}/{}", addr, prefix).into());
            add_args.push("ipv4.method".into());
            add_args.push("manual".into());
            if let Some(gw) = &v4f.gateway {
                if !gw.is_empty() {
                    let extra_routes = extra_default_routes(&args.net_device);
                    if !extra_routes.is_empty() {
                        eprintln!("[WARNING] system has extra default routes on other devices:");
                        for r in &extra_routes {
                            eprintln!("[WARNING]     {}", r);
                        }
                    }
                    add_args.push("ipv4.gateway".into());
                    add_args.push(gw.clone().into());
                }
            }
            if let Some(dns) = &v4f.dns {
                if !dns.is_empty() {
                    add_args.push("ipv4.dns".into());
                    add_args.push(dns.clone().into());
                }
            }
            // 静态路由
            if let (Some(to), Some(prefix)) = (&rp.to, &rp.to_prefix) {
                let mut entry = format!("{}/{}", to, prefix);
                if let Some(via) = &rp.via {
                    entry.push_str(&format!(" {}", via));
                }
                if let Some(t) = &rp.table {
                    entry.push_str(&format!(" {}", t));
                }
                add_args.push("ipv4.routes".into());
                add_args.push(entry.into());
            }
            // 路由策略
            if rp.rule_from.is_some() || rp.rule_to.is_some() {
                let mut rules: Vec<String> = Vec::new();
                if let Some(t) = &rp.table {
                    if let Some(rf) = &rp.rule_from {
                        let from_str = match &rp.rule_from_prefix {
                            Some(px) => format!("{}/{}", rf, px),
                            None => rf.clone(),
                        };
                        rules.push(format!("from {} table {}", from_str, t));
                    }
                    if let Some(rt) = &rp.rule_to {
                        let to_str = match &rp.rule_to_prefix {
                            Some(px) => format!("{}/{}", rt, px),
                            None => rt.clone(),
                        };
                        rules.push(format!("to {} table {}", to_str, t));
                    }
                } else {
                    eprintln!("[WARNING] routing-policy without a table is meaningless; skipping nmcli routing-rules");
                }
                if !rules.is_empty() {
                    add_args.push("ipv4.routing-rules".into());
                    add_args.push(rules.join(", ").into());
                }
            }
        }
    }

    // IPv6
    if let Some(v6f) = v6 {
        if v6f.is_dhcp {
            add_args.push("ipv6.method".into());
            add_args.push("auto".into());
        } else if let Some(addr) = &v6f.addr {
            let prefix = v6f
                .netmask
                .as_deref()
                .map(|m| m.parse::<u8>().unwrap_or(128))
                .unwrap_or(128);
            add_args.push("ipv6.addresses".into());
            add_args.push(format!("{}/{}", addr, prefix));
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

    let status = Command::new("nmcli").args(&add_args).status();
    if let Ok(s) = status {
        if s.success() {
            let _ = Command::new("nmcli")
                .args(["con", "up", &con_name])
                .status();
            println!("[INFO] nmcli configuration applied successfully");
        } else {
            eprintln!("[ERROR] Failed to apply nmcli configuration");
        }
    } else {
        eprintln!("[ERROR] Could not run nmcli");
    }
}

/// 使用 systemd-networkd 配置网络
fn configure_with_networkd(args: &Args, v4: &Option<IpFamily>, v6: &Option<IpFamily>, rp: &RoutesPolicy) {
    let file_path = format!("/etc/systemd/network/10-{}.network", args.net_device);
    let mut file =
        fs::File::create(&file_path).expect("[ERROR] Failed to create networkd config file");

    writeln!(file, "[Match]").unwrap();
    writeln!(file, "Name={}", args.net_device).unwrap();
    writeln!(file).unwrap();

    writeln!(file, "[Network]").unwrap();

    // IPv4
    if let Some(v4f) = v4 {
        if v4f.is_dhcp {
            writeln!(file, "DHCP=ipv4").unwrap();
        } else if let Some(addr) = &v4f.addr {
            let prefix = v4f.netmask.as_deref().map(mask_to_prefix).unwrap_or(32);
            writeln!(file, "Address={}/{}", addr, prefix).unwrap();
        }
        if let Some(gw) = &v4f.gateway {
            if !gw.is_empty() {
                writeln!(file, "Gateway={}", gw).unwrap();
            }
        }
    }

    // IPv6
    if let Some(v6f) = v6 {
        if v6f.is_dhcp {
            writeln!(file, "DHCP=ipv6").unwrap();
        } else if let Some(addr) = &v6f.addr {
            let prefix = v6f
                .netmask
                .as_deref()
                .map(|m| m.parse::<u8>().unwrap_or(128))
                .unwrap_or(128);
            writeln!(file, "Address={}/{}", addr, prefix).unwrap();
        }
        if let Some(gw) = &v6f.gateway {
            if !gw.is_empty() {
                writeln!(file, "Gateway={}", gw).unwrap();
            }
        }
    }

    let mut dns_list = Vec::new();
    if let Some(v4f) = v4 {
        if let Some(d) = &v4f.dns {
            if !d.is_empty() {
                dns_list.push(d.clone());
            }
        }
    }
    if let Some(v6f) = v6 {
        if let Some(d) = &v6f.dns {
            if !d.is_empty() {
                dns_list.push(d.clone());
            }
        }
    }
    if !dns_list.is_empty() {
        writeln!(file, "DNS={}", dns_list.join(" ")).unwrap();
    }

    // 静态路由([Route] 段)
    if let (Some(to), Some(prefix)) = (&rp.to, &rp.to_prefix) {
        writeln!(file).unwrap();
        writeln!(file, "[Route]").unwrap();
        writeln!(file, "Destination={}/{}", to, prefix).unwrap();
        if let Some(via) = &rp.via {
            writeln!(file, "Gateway={}", via).unwrap();
        }
        if let Some(t) = &rp.table {
            writeln!(file, "Table={}", t).unwrap();
        }
    }

    // 路由策略([RoutingPolicyRule] 段)
    if rp.rule_from.is_some() || rp.rule_to.is_some() {
        if rp.table.is_none() {
            eprintln!("[WARNING] routing-policy without a table is meaningless; skipping networkd policy rules");
        } else {
            let t = rp.table.as_deref().unwrap();
            if let Some(rf) = &rp.rule_from {
                let from_str = match &rp.rule_from_prefix {
                    Some(px) => format!("{}/{}", rf, px),
                    None => rf.clone(),
                };
                writeln!(file).unwrap();
                writeln!(file, "[RoutingPolicyRule]").unwrap();
                writeln!(file, "From={}", from_str).unwrap();
                writeln!(file, "Table={}", t).unwrap();
            }
            if let Some(rt) = &rp.rule_to {
                let to_str = match &rp.rule_to_prefix {
                    Some(px) => format!("{}/{}", rt, px),
                    None => rt.clone(),
                };
                writeln!(file).unwrap();
                writeln!(file, "[RoutingPolicyRule]").unwrap();
                writeln!(file, "To={}", to_str).unwrap();
                writeln!(file, "Table={}", t).unwrap();
            }
        }
    }

    println!("[INFO] Created systemd-networkd config at {}", file_path);

    let status = Command::new("systemctl")
        .args(["restart", "systemd-networkd"])
        .status();
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

/// 使用 ip 命令手动配置 IP
fn configure_with_ip(args: &Args, v4: &Option<IpFamily>, v6: &Option<IpFamily>, rp: &RoutesPolicy) {
    let any_dhcp = v4.as_ref().map(|f| f.is_dhcp).unwrap_or(false)
        || v6.as_ref().map(|f| f.is_dhcp).unwrap_or(false);
    if any_dhcp {
        eprintln!("[ERROR] DHCP is not supported when using manual IP configuration");
        return;
    }

    let _ = Command::new("ip")
        .args(["addr", "flush", "dev", &args.net_device])
        .status();

    // IPv4
    if let Some(v4f) = v4 {
        if let Some(addr) = &v4f.addr {
            let prefix = v4f.netmask.as_deref().map(mask_to_prefix).unwrap_or(32);
            let status = Command::new("ip")
                .args([
                    "addr",
                    "add",
                    &format!("{}/{}", addr, prefix),
                    "dev",
                    &args.net_device,
                ])
                .status();
            if let Ok(s) = status {
                if !s.success() {
                    eprintln!("[ERROR] Failed to configure IPv4 address");
                }
            } else {
                eprintln!("[ERROR] Could not run ip command for IPv4");
            }
        }
        if let Some(gw) = &v4f.gateway {
            if !gw.is_empty() {
                let _ = Command::new("ip")
                    .args(["route", "add", "default", "via", gw, "dev", &args.net_device])
                    .status();
            }
        }
    }

    // IPv6
    if let Some(v6f) = v6 {
        if let Some(addr) = &v6f.addr {
            let prefix = v6f
                .netmask
                .as_deref()
                .map(|m| m.parse::<u8>().unwrap_or(128))
                .unwrap_or(128);
            let status = Command::new("ip")
                .args([
                    "addr",
                    "add",
                    &format!("{}/{}", addr, prefix),
                    "dev",
                    &args.net_device,
                ])
                .status();
            if let Ok(s) = status {
                if !s.success() {
                    eprintln!("[ERROR] Failed to configure IPv6 address");
                }
            } else {
                eprintln!("[ERROR] Could not run ip command for IPv6");
            }
        }
    }

    // 静态路由
    if let (Some(to), Some(prefix)) = (&rp.to, &rp.to_prefix) {
        let mut route_args: Vec<String> = vec!["route".into(), "add".into()];
        route_args.push(format!("{}/{}", to, prefix));
        if let Some(via) = &rp.via {
            route_args.push("via".into());
            route_args.push(via.clone());
        }
        route_args.push("dev".into());
        route_args.push(args.net_device.clone());
        if let Some(t) = &rp.table {
            route_args.push("table".into());
            route_args.push(t.clone());
        }
        let _ = Command::new("ip").args(&route_args).status();
    }

    // 路由策略
    if rp.rule_from.is_some() || rp.rule_to.is_some() {
        if rp.table.is_none() {
            eprintln!("[WARNING] routing-policy without a table is meaningless; skipping ip rules");
        } else {
            let t = rp.table.as_deref().unwrap();
            if let Some(rf) = &rp.rule_from {
                let from_str = match &rp.rule_from_prefix {
                    Some(px) => format!("{}/{}", rf, px),
                    None => rf.clone(),
                };
                let _ = Command::new("ip")
                    .args(["rule", "add", "from", &from_str, "table", t])
                    .status();
            }
            if let Some(rt) = &rp.rule_to {
                let to_str = match &rp.rule_to_prefix {
                    Some(px) => format!("{}/{}", rt, px),
                    None => rt.clone(),
                };
                let _ = Command::new("ip")
                    .args(["rule", "add", "to", &to_str, "table", t])
                    .status();
            }
        }
    }

    let status = Command::new("ip")
        .args(["link", "set", "dev", &args.net_device, "up"])
        .status();
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
