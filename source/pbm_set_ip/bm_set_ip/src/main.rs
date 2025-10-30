use lexopt;
use serde_yaml;
use serde_yaml::{Mapping, Value};
use std::env;
use std::fs;
use std::io::Write;
use std::process::exit;
use std::process::Command;

/// 命令行参数定义
struct Args {
    /// 网卡名
    net_device: String,
    /// IPv4 地址或dhcp
    ip: String,
    /// IPv4 掩码或前缀长度
    netmask: String,
    /// IPv4 网关，可为空
    gateway: Option<String>,
    /// IPv4 DNS，可为空
    dns: Option<String>,
    /// IPv6 地址或dhcp，可为空
    ipv6: Option<String>,
    /// IPv6 前缀长度，可为空
    ipv6_prefix: Option<String>,
    /// IPv6 网关，可为空
    ipv6_gateway: Option<String>,
    /// IPv6 DNS，可为空
    ipv6_dns: Option<String>,
}

impl Args {
    fn parse() -> Result<Self, lexopt::Error> {
        use lexopt::prelude::*;

        let mut net_device = None;
        let mut ip = None;
        let mut netmask = None;
        let mut gateway = None;
        let mut dns = None;
        let mut ipv6 = None;
        let mut ipv6_prefix = None;
        let mut ipv6_gateway = None;
        let mut ipv6_dns = None;

        let mut parser = lexopt::Parser::from_env();
        while let Some(arg) = parser.next()? {
            match arg.clone() {
                // 位置参数处理
                Value(val) if net_device.is_none() => {
                    net_device = Some(val.into_string()?);
                }
                Value(val) if ip.is_none() => {
                    ip = Some(val.into_string()?);
                }
                Value(val) if netmask.is_none() => {
                    netmask = Some(val.into_string()?);
                }
                Value(val) => {
                    // 按顺序处理可选参数
                    if gateway.is_none() {
                        gateway = Some(val.into_string()?);
                    } else if dns.is_none() {
                        dns = Some(val.into_string()?);
                    } else if ipv6.is_none() {
                        ipv6 = Some(val.into_string()?);
                    } else if ipv6_prefix.is_none() {
                        ipv6_prefix = Some(val.into_string()?);
                    } else if ipv6_gateway.is_none() {
                        ipv6_gateway = Some(val.into_string()?);
                    } else if ipv6_dns.is_none() {
                        ipv6_dns = Some(val.into_string()?);
                    } else {
                        return Err(arg.unexpected());
                    }
                }
                _ => return Err(arg.unexpected()),
            }
        }

        Ok(Args {
            net_device: net_device.ok_or("missing required argument: net_device")?,
            ip: ip.ok_or("missing required argument: ip")?,
            netmask: netmask.ok_or("missing required argument: netmask")?,
            gateway,
            dns,
            ipv6,
            ipv6_prefix,
            ipv6_gateway,
            ipv6_dns,
        })
    }
}

#[derive(Debug)]
enum NetManager {
    Netplan,
    NetworkManager,
    SystemdNetworkd,
    Unknown,
}

fn main() {
    if !is_root() {
        let exe = env::current_exe().unwrap();
        let args: Vec<String> = env::args().skip(1).collect();
        let status = Command::new("sudo")
            .arg(exe)
            .args(&args)
            .status()
            .expect("failed to execute sudo");
        exit(status.code().unwrap_or(1));
    }
    println!("bm_set_ip version: {}", concat!(env!("GIT_TAG_COMMIT")));

    let mut args = match Args::parse() {
        Ok(args) => args,
        Err(e) => {
            eprintln!("Error: {}", e);
            eprintln!("\nUsage: {} <net_device> <ip> <netmask> [gateway] [dns] [ipv6] [ipv6_prefix] [ipv6_gateway] [ipv6_dns]", 
                env::args().next().unwrap_or("bm_set_ip".into()));
            eprintln!("\nExamples:");
            eprintln!("  DHCP IPv4:         bm_set_ip eth0 dhcp ''");
            eprintln!("  DHCP IPv4+IPv6:    bm_set_ip eth0 dhcp '' '' '' dhcp");
            eprintln!("  Static IPv4:       bm_set_ip eth0 192.168.1.100 24 192.168.1.1");
            eprintln!("  Static IPv4+IPv6:  bm_set_ip eth0 192.168.1.100 24 192.168.1.1 8.8.8.8 2001:db8::1 64 fe80::1");
            exit(1);
        }
    };

    // 判断是否为dhcp模式
    let is_dhcp = args.ip.to_lowercase() == "dhcp" || args.ip.to_lowercase() == "auto";
    let is_dhcp6 = args
        .ipv6
        .as_deref()
        .map(|v| v.to_lowercase() == "dhcp" || v.to_lowercase() == "auto")
        .unwrap_or(false);
    // 处理 netmask 支持数字
    if !is_dhcp {
        if args.netmask.parse::<u8>().is_ok() {
            // 如果是数字，转为掩码字符串
            let mask = prefix_to_mask(args.netmask.parse::<u8>().unwrap());
            args.netmask = mask;
        }
    }

    let net_manager = detect_net_manager();
    match net_manager {
        NetManager::Netplan => {
            println!("[INFO] Using netplan for network configuration");
            configure_with_netplan(&args, is_dhcp, is_dhcp6);
        }
        NetManager::NetworkManager => {
            println!("[INFO] Using NetworkManager (nmcli) for network configuration");
            configure_with_nmcli(&args, is_dhcp, is_dhcp6);
        }
        NetManager::SystemdNetworkd => {
            println!("[INFO] Using systemd-networkd for network configuration");
            configure_with_networkd(&args, is_dhcp, is_dhcp6);
        }
        NetManager::Unknown => {
            eprintln!("[ERROR] Could not detect a supported network manager!");
            eprintln!("[INFO] Trying to configure IP manually using ip command");
            configure_with_ip(&args, is_dhcp, is_dhcp6);
        }
    }
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

/// 将数字前缀转为掩码字符串
fn prefix_to_mask(prefix: u8) -> String {
    let mask = if prefix > 32 { 32 } else { prefix };
    let mut res = vec![];
    let mut bits = mask;
    for _ in 0..4 {
        let val = if bits >= 8 {
            255
        } else if bits == 0 {
            0
        } else {
            (!0u8) << (8 - bits)
        };
        res.push(val);
        if bits >= 8 {
            bits -= 8;
        } else {
            bits = 0;
        }
    }
    res.iter()
        .map(|v| v.to_string())
        .collect::<Vec<_>>()
        .join(".")
}

/// 掩码字符串转前缀
fn mask_to_prefix(mask: &str) -> u8 {
    if let Ok(prefix) = mask.parse::<u8>() {
        // 允许直接给数字
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
    // 优先检测 netplan
    if is_command_exists("netplan") {
        return NetManager::Netplan;
    }
    // 检查 NetworkManager
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
    // 检查 systemd-networkd
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

/// 判断是否是root权限
fn is_root() -> bool {
    unsafe { libc::geteuid() == 0 }
}

/// 获取netplan配置文件中的ethernets
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
fn configure_with_netplan(args: &Args, is_dhcp: bool, is_dhcp6: bool) {
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
            panic!("[ERROR] YAML parsing aborted"); // or return Err(e.into());
        }
    };

    // network -> ethernets -> <dev>
    let network_map = doc.as_mapping_mut().unwrap();
    let ethernets_map = get_or_create_mapping(network_map, "network");
    let ethernets = get_or_create_mapping(ethernets_map, "ethernets");

    let dev = args.net_device.clone();
    let mut dev_cfg = serde_yaml::Mapping::new();

    if is_dhcp {
        let extra_routes = extra_default_routes(&args.net_device);
        if !extra_routes.is_empty() {
            eprintln!("[WARNING] system has extra default routes on other devices:");
            for r in &extra_routes {
                eprintln!("[WARNING]     {}", r);
            }
        }
        dev_cfg.remove(&serde_yaml::Value::String("addresses".into()));
        dev_cfg.remove(&serde_yaml::Value::String("gateway4".into()));
        dev_cfg.remove(&serde_yaml::Value::String("nameservers".into()));
        dev_cfg.remove(&serde_yaml::Value::String("dhcp4".into()));
        dev_cfg.insert(
            serde_yaml::Value::String("dhcp4".into()),
            serde_yaml::Value::Bool(true),
        );
    } else {
        // IPv4
        let ipv4_addr = format!("{}/{}", args.ip, mask_to_prefix(&args.netmask));
        let addresses = vec![serde_yaml::Value::String(ipv4_addr.clone())];
        dev_cfg.insert(
            serde_yaml::Value::String("dhcp4".into()),
            serde_yaml::Value::Bool(false),
        );
        if let Some(gw) = &args.gateway {
            if !gw.is_empty() {
                let extra_routes = extra_default_routes(&args.net_device);
                if !extra_routes.is_empty() {
                    eprintln!("[WARNING] system has extra default routes on other devices:");
                    for r in &extra_routes {
                        eprintln!("[WARNING]     {}", r);
                    }
                }
                dev_cfg.insert(
                    serde_yaml::Value::String("gateway4".into()),
                    serde_yaml::Value::String(gw.clone()),
                );
            }
        }
        dev_cfg.insert(
            serde_yaml::Value::String("addresses".into()),
            serde_yaml::Value::Sequence(addresses),
        );
    }

    // IPv6
    if is_dhcp6 {
        dev_cfg.remove(&serde_yaml::Value::String("gateway6".into()));
        dev_cfg.remove(&serde_yaml::Value::String("dhcp6".into()));
        dev_cfg.insert(
            serde_yaml::Value::String("dhcp6".into()),
            serde_yaml::Value::Bool(true),
        );
    } else if let (Some(ipv6), Some(prefix)) = (&args.ipv6, &args.ipv6_prefix) {
        if !ipv6.is_empty() && !prefix.is_empty() {
            let ipv6_addr = format!("{}/{}", ipv6, prefix);
            dev_cfg.insert(
                serde_yaml::Value::String("dhcp6".into()),
                serde_yaml::Value::Bool(false),
            );
            dev_cfg.insert(
                serde_yaml::Value::String("addresses".into()),
                serde_yaml::Value::Sequence(vec![serde_yaml::Value::String(ipv6_addr)]),
            );
            if let Some(ipv6_gw) = &args.ipv6_gateway {
                if !ipv6_gw.is_empty() {
                    dev_cfg.insert(
                        serde_yaml::Value::String("gateway6".into()),
                        serde_yaml::Value::String(ipv6_gw.clone()),
                    );
                }
            }
        }
    }

    // DNS
    let mut dns_list = Vec::new();
    if let Some(dns) = &args.dns {
        if !dns.is_empty() {
            dns_list.push(serde_yaml::Value::String(dns.clone()));
        }
    }
    if let Some(ipv6_dns) = &args.ipv6_dns {
        if !ipv6_dns.is_empty() {
            dns_list.push(serde_yaml::Value::String(ipv6_dns.clone()));
        }
    }
    if !dns_list.is_empty() {
        let mut dns_map = serde_yaml::Mapping::new();
        dns_map.insert(
            serde_yaml::Value::String("addresses".into()),
            serde_yaml::Value::Sequence(dns_list),
        );
        dev_cfg.insert(
            serde_yaml::Value::String("nameservers".into()),
            serde_yaml::Value::Mapping(dns_map),
        );
    }

    dev_cfg.insert(
        serde_yaml::Value::String("optional".into()),
        serde_yaml::Value::String("yes".into()),
    );
    println!("[INFO] Add config: {:?}", dev_cfg);

    ethernets.insert(
        serde_yaml::Value::String(dev),
        serde_yaml::Value::Mapping(dev_cfg),
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
fn configure_with_nmcli(args: &Args, is_dhcp: bool, is_dhcp6: bool) {
    let con_name = format!("static-{}", &args.net_device);

    // 删除同名连接（如果存在）
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
        (&con_name).clone().into(),
        "connection.autoconnect-priority".into(),
        "10".into(),
    ];

    if is_dhcp {
        let extra_routes = extra_default_routes(&args.net_device);
        if !extra_routes.is_empty() {
            eprintln!("[WARNING] system has extra default routes on other devices:");
            for r in &extra_routes {
                eprintln!("[WARNING]     {}", r);
            }
        }
        add_args.push("ipv4.method".into());
        add_args.push("auto".into());
    } else {
        let full_ip = format!("{}/{}", args.ip, mask_to_prefix(&args.netmask));
        add_args.push("ipv4.addresses".into());
        add_args.push(full_ip.into());
        add_args.push("ipv4.method".into());
        add_args.push("manual".into());

        if let Some(gw) = &args.gateway {
            if !gw.is_empty() {
                let extra_routes = extra_default_routes(&args.net_device);
                if !extra_routes.is_empty() {
                    eprintln!("[WARNING] system has extra default routes on other devices:");
                    for r in &extra_routes {
                        eprintln!("[WARNING]     {}", r);
                    }
                }
                add_args.push("ipv4.gateway".into());
                add_args.push(gw.into());
            }
        }
        if let Some(dns) = &args.dns {
            if !dns.is_empty() {
                add_args.push("ipv4.dns".into());
                add_args.push(dns.into());
            }
        }
    }

    // IPv6
    if is_dhcp6 {
        add_args.push("ipv6.method".into());
        add_args.push("auto".into());
    } else if let (Some(ipv6), Some(prefix)) = (&args.ipv6, &args.ipv6_prefix) {
        if !ipv6.is_empty() && !prefix.is_empty() {
            add_args.push("ipv6.addresses".into());
            add_args.push(format!("{}/{}", ipv6, prefix));
            add_args.push("ipv6.method".into());
            add_args.push("manual".into());
            if let Some(ipv6_gw) = &args.ipv6_gateway {
                if !ipv6_gw.is_empty() {
                    add_args.push("ipv6.gateway".into());
                    add_args.push(ipv6_gw.into());
                }
            }
            if let Some(ipv6_dns) = &args.ipv6_dns {
                if !ipv6_dns.is_empty() {
                    add_args.push("ipv6.dns".into());
                    add_args.push(ipv6_dns.into());
                }
            }
        }
    }

    let status = Command::new("nmcli").args(&add_args).status();
    if let Ok(s) = status {
        if s.success() {
            // 激活连接
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
fn configure_with_networkd(args: &Args, is_dhcp: bool, is_dhcp6: bool) {
    let file_path = format!("/etc/systemd/network/10-{}.network", args.net_device);

    let mut file =
        fs::File::create(&file_path).expect("[ERROR] Failed to create networkd config file");

    writeln!(file, "[Match]").unwrap();
    writeln!(file, "Name={}", args.net_device).unwrap();
    writeln!(file).unwrap();

    writeln!(file, "[Network]").unwrap();

    if is_dhcp {
        writeln!(file, "DHCP=ipv4").unwrap();
    } else {
        let prefix = mask_to_prefix(&args.netmask);
        writeln!(file, "Address={}/{}", args.ip, prefix).unwrap();
    }

    if is_dhcp6 {
        writeln!(file, "DHCP=ipv6").unwrap();
    } else if let (Some(ipv6), Some(prefix)) = (&args.ipv6, &args.ipv6_prefix) {
        if !ipv6.is_empty() && !prefix.is_empty() {
            writeln!(file, "Address={}/{}", ipv6, prefix).unwrap();
        }
    }

    if let Some(gw) = &args.gateway {
        if !gw.is_empty() {
            writeln!(file, "Gateway={}", gw).unwrap();
        }
    }

    if let Some(ipv6_gw) = &args.ipv6_gateway {
        if !ipv6_gw.is_empty() {
            writeln!(file, "Gateway={}", ipv6_gw).unwrap();
        }
    }

    let mut dns_list = Vec::new();
    if let Some(dns) = &args.dns {
        if !dns.is_empty() {
            dns_list.push(dns.clone());
        }
    }
    if let Some(ipv6_dns) = &args.ipv6_dns {
        if !ipv6_dns.is_empty() {
            dns_list.push(ipv6_dns.clone());
        }
    }
    if !dns_list.is_empty() {
        writeln!(file, "DNS={}", dns_list.join(" ")).unwrap();
    }

    println!("[INFO] Created systemd-networkd config at {}", file_path);

    // 重启 systemd-networkd 服务
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
fn configure_with_ip(args: &Args, is_dhcp: bool, is_dhcp6: bool) {
    if is_dhcp || is_dhcp6 {
        eprintln!("[ERROR] DHCP is not supported when using manual IP configuration");
        return;
    }

    // 清除现有地址
    let _ = Command::new("ip")
        .args(["addr", "flush", "dev", &args.net_device])
        .status();

    // 配置 IPv4
    if !args.ip.is_empty() && !args.netmask.is_empty() {
        let prefix = mask_to_prefix(&args.netmask);
        let status = Command::new("ip")
            .args([
                "addr",
                "add",
                &format!("{}/{}", args.ip, prefix),
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

    // 配置 IPv6
    if let (Some(ipv6), Some(prefix)) = (&args.ipv6, &args.ipv6_prefix) {
        if !ipv6.is_empty() && !prefix.is_empty() {
            let status = Command::new("ip")
                .args([
                    "addr",
                    "add",
                    &format!("{}/{}", ipv6, prefix),
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

    // 启用接口
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
