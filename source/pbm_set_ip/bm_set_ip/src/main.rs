use clap::Parser;
use serde_yaml;
use std::env;
use std::fs;
use std::process::Command;
use std::process::exit;
use which::which;

/// 命令行参数定义
#[derive(Parser, Debug)]
#[command(
    author,
    version = concat!(env!("GIT_TAG_COMMIT")),
    about = "配置网卡的 IPv4/IPv6 参数（支持 netplan 和 NetworkManager）

使用示例：
  配置静态 IPv4 地址（无网关）:
    bm_set_ip eth1 192.168.150.1 255.255.255.0

  配置 DHCP:
    bm_set_ip eth0 dhcp ''

  配置静态 IPv4 和 IPv6 地址（有网关）:
    bm_set_ip eth0 192.168.1.100 24 192.168.1.1 8.8.8.8 2001:db8::1 64 fe80::1 240e:8::8
"
)]
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

#[derive(Debug)]
enum NetManager {
    Netplan,
    NetworkManager,
    Unknown,
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
    if which("netplan").is_ok() {
        return NetManager::Netplan;
    }
    // 检查 NetworkManager
    if which("nmcli").is_ok() {
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
    NetManager::Unknown
}

/// 判断是否是root权限
fn is_root() -> bool {
    unsafe { libc::geteuid() == 0 }
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

    let mut args = Args::parse();

    // 判断是否为dhcp模式
    let is_dhcp = args.ip.to_lowercase() == "dhcp" || args.ip.to_lowercase() == "auto";
    let is_dhcp6 = args
        .ipv6
        .as_deref()
        .map(|v| (v.to_lowercase() == "dhcp" || v.to_lowercase() == "auto"))
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
        NetManager::Unknown => {
            eprintln!("[ERROR] Could not detect a supported network manager!");
        }
    }
}

/// 配置 netplan
fn configure_with_netplan(args: &Args, is_dhcp: bool, is_dhcp6: bool) {
    let file_path = "/etc/netplan/01-netcfg.yaml";
    if fs::File::open(file_path).is_err() {
        eprintln!("[ERROR] Error: Cannot read {}", file_path);
        std::process::exit(1);
    }
    let content = fs::read_to_string(file_path)
        .unwrap_or_else(|_| String::from("network:\n  version: 2\n  ethernets: {}\n"));
    let mut doc: serde_yaml::Value = match serde_yaml::from_str(&content) {
        Ok(doc) => doc,
        Err(e) => {
            eprintln!(
                "YAML parsing failed: {}\nError location: {:?}",
                e,
                e.location()
            );
            panic!("YAML parsing aborted"); // or return Err(e.into());
        }
    };

    // network -> ethernets -> <dev>
    let ethernets = doc
        .get_mut("network")
        .and_then(|n| n.get_mut("ethernets"))
        .and_then(|e| e.as_mapping_mut())
        .expect("Could not find 'ethernets' section in netplan config");

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
