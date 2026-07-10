//! bm_set_ip 组模式解析器集成测试(通过 --dry-run 无实施模式驱动)。
//! 覆盖:7 种配置模式变体 / family2 门位置 / dhcp 大小写 / 掩码格式转换 /
//!       IPv6 地址格式 / 部分路由 / 部分策略 / v6+路由 / dns1-v6 边 / 空 net_device /
//!       异常错误 / 残留参数告警
//!
//! 运行:`cargo test --test parse_cases`
//! 也可经 `bash tests/parse_cases.sh` 调用(薄包装)。

use std::process::Command;

/// 以 --dry-run 运行二进制,返回合并的 stdout+stderr。
fn dry_run(args: &[&str]) -> String {
    let bin = std::env::var("CARGO_BIN_EXE_bm_set_ip")
        .expect("CARGO_BIN_EXE_bm_set_ip not set; run via `cargo test`");
    let mut cmd = Command::new(&bin);
    cmd.arg("--dry-run");
    cmd.args(args);
    let out = cmd
        .output()
        .unwrap_or_else(|e| panic!("failed to run {}: {}", bin, e));
    let mut s = String::from_utf8_lossy(&out.stdout).into_owned();
    s.push_str(&String::from_utf8_lossy(&out.stderr));
    s
}

/// 精确断言:输出含整行 `expected`(key=value)。
fn assert_line(out: &str, expected: &str) {
    assert!(
        out.lines().any(|l| l == expected),
        "expected line {:?}\nfull output:\n{}",
        expected,
        out
    );
}

/// 子串断言:输出(含 stderr)含子串。
fn assert_sub(out: &str, expected: &str) {
    assert!(
        out.contains(expected),
        "expected substring {:?}\nfull output:\n{}",
        expected,
        out
    );
}

/// 错误断言:非零退出 + 输出含子串。
fn assert_err(args: &[&str], expected: &str) {
    let bin = std::env::var("CARGO_BIN_EXE_bm_set_ip").unwrap();
    let out = Command::new(&bin)
        .arg("--dry-run")
        .args(args)
        .output()
        .unwrap();
    let combined = {
        let mut s = String::from_utf8_lossy(&out.stdout).into_owned();
        s.push_str(&String::from_utf8_lossy(&out.stderr));
        s
    };
    assert!(
        !out.status.success(),
        "expected non-zero exit, got success\nargs: {:?}\noutput:\n{}",
        args,
        combined
    );
    assert!(
        combined.contains(expected),
        "expected error substring {:?}\nargs: {:?}\noutput:\n{}",
        expected,
        args,
        combined
    );
}

// ---- 精确断言用例(整行匹配)----
macro_rules! case {
    ($name:ident, $args:expr, [$($exp:literal),* $(,)?]) => {
        #[test]
        fn $name() {
            let out = dry_run($args);
            $( assert_line(&out, $exp); )*
        }
    };
}

// ---- 子串断言用例(残留告警等)----
macro_rules! case_sub {
    ($name:ident, $args:expr, [$($exp:literal),* $(,)?]) => {
        #[test]
        fn $name() {
            let out = dry_run($args);
            $( assert_sub(&out, $exp); )*
        }
    };
}

// ---- 错误断言用例 ----
macro_rules! case_err {
    ($name:ident, $args:expr, $exp:literal) => {
        #[test]
        fn $name() {
            assert_err($args, $exp);
        }
    };
}

// ============ A. 7 种标准模式 ============
case!(a1_v4_only, &["eth0","1.1.1.1","24","1.1.1.254","8.8.8.8"], [
    "family1_is_v6=false", "v4.present=true", "v4.addr=1.1.1.1", "v4.netmask=24",
    "v4.gateway=1.1.1.254", "v4.dns=8.8.8.8", "v4.is_dhcp=false", "v6.present=false", "routes.to=",
]);
case!(a1_v4_minimal, &["eth0","1.1.1.1","24"], [
    "v4.addr=1.1.1.1", "v4.gateway=", "v4.dns=", "v6.present=false",
]);
case!(a1_v4_gw_no_dns, &["eth0","1.1.1.1","24","1.1.1.254"], ["v4.gateway=1.1.1.254", "v4.dns="]);
case!(a2_v6_only, &["eth0","2001:db8::1","64","fe80::1","2001:4860:4860::8888"], [
    "family1_is_v6=true", "v4.present=false", "v6.present=true", "v6.addr=2001:db8::1",
    "v6.prefix=64", "v6.gateway=fe80::1", "v6.dns=2001:4860:4860::8888", "v6.is_dhcp=false",
]);
case!(a2_v6_addr_prefix, &["eth0","2001:db8::1","64"], [
    "family1_is_v6=true", "v6.addr=2001:db8::1", "v6.prefix=64", "v6.gateway=", "v4.present=false",
]);
case!(a2_v6_addr_no_prefix, &["eth0","2001:db8::1"], ["family1_is_v6=true", "v6.addr=2001:db8::1", "v6.prefix="]);
case!(a3_v4_v6, &["eth0","1.1.1.1","24","1.1.1.254","8.8.8.8","2001:db8::1","64","fe80::1"], [
    "v4.present=true", "v4.addr=1.1.1.1", "v4.dns=8.8.8.8",
    "v6.present=true", "v6.addr=2001:db8::1", "v6.prefix=64", "v6.gateway=fe80::1",
]);
case!(a4_v4_v6_routes_policy, &["eth0","1.1.1.1","24","","","192.168.2.0","24","1.1.1.254","100","10.0.0.0","24","192.168.3.0","24","2001:db8::1","64"], [
    "v4.addr=1.1.1.1", "v6.present=true", "v6.addr=2001:db8::1",
    "routes.to=192.168.2.0", "routes.to_prefix=24", "routes.via=1.1.1.254", "routes.table=100",
    "policy.rule_from=10.0.0.0", "policy.rule_from_prefix=24",
    "policy.rule_to=192.168.3.0", "policy.rule_to_prefix=24",
]);
case!(a5_v4_routes_skip, &["eth0","1.1.1.1","24","","","192.168.2.0","24","1.1.1.254","100"], [
    "v4.gateway=", "v4.dns=", "v6.present=false",
    "routes.to=192.168.2.0", "routes.to_prefix=24", "routes.via=1.1.1.254", "routes.table=100",
]);
case!(a6_v4_dhcp, &["eth0","dhcp",""], [
    "family1_is_v6=false", "v4.present=true", "v4.addr=dhcp", "v4.is_dhcp=true", "v4.netmask=", "v6.present=false",
]);
case!(a7_dual_dhcp, &["eth0","dhcp","","","","dhcp"], ["v4.is_dhcp=true", "v6.present=true", "v6.addr=dhcp", "v6.is_dhcp=true"]);

// ============ B. family2 门触发位置 ============
case!(b1_gate_after_mask, &["eth0","1.1.1.1","24","2001:db8::1","64"], [
    "v4.addr=1.1.1.1", "v4.netmask=24", "v4.gateway=", "v6.addr=2001:db8::1", "v6.prefix=64",
]);
case!(b2_gate_after_gw, &["eth0","1.1.1.1","24","1.1.1.254","2001:db8::1","64"], [
    "v4.gateway=1.1.1.254", "v4.dns=", "v6.addr=2001:db8::1", "v6.prefix=64",
]);
case!(b3_gate_after_dns_skip_routes, &["eth0","1.1.1.1","24","1.1.1.254","8.8.8.8","2001:db8::1","64"], [
    "v4.dns=8.8.8.8", "routes.to=", "v6.addr=2001:db8::1",
]);
case!(b4_gate_after_table_skip_policy, &["eth0","1.1.1.1","24","","","192.168.2.0","24","1.1.1.254","100","2001:db8::1","64"], [
    "routes.table=100", "policy.rule_from=", "v6.addr=2001:db8::1",
]);
case!(b5_gate_after_policy, &["eth0","1.1.1.1","24","","","192.168.2.0","24","1.1.1.254","100","10.0.0.0","24","192.168.3.0","24","2001:db8::1","64"], [
    "policy.rule_to_prefix=24", "v6.addr=2001:db8::1",
]);

// ============ C. dhcp / auto 大小写 ============
case!(c1_dhcp_uppercase, &["eth0","DHCP",""], ["v4.is_dhcp=true", "v4.addr=DHCP"]);
case!(c2_auto_v4, &["eth0","auto",""], ["v4.is_dhcp=true", "v4.addr=auto"]);
case!(c3_auto_v6, &["eth0","dhcp","","","","AUTO"], ["v6.is_dhcp=true", "v6.addr=AUTO"]);
case!(c4_v4_dhcp_v6_static, &["eth0","dhcp","","","","2001:db8::1","64"], [
    "v4.is_dhcp=true", "v6.addr=2001:db8::1", "v6.is_dhcp=false",
]);
case!(c5_v4_static_v6_dhcp, &["eth0","1.1.1.1","24","1.1.1.254","8.8.8.8","dhcp",""], [
    "v4.is_dhcp=false", "v6.is_dhcp=true", "v6.addr=dhcp", "v4.dns=8.8.8.8",
]);

// ============ D. 掩码格式转换 ============
case!(d1_v4_netmask_dotted_raw, &["eth0","1.1.1.1","255.255.255.0"], ["v4.netmask=255.255.255.0"]);
case!(d2_v4_netmask_prefix_raw, &["eth0","1.1.1.1","24"], ["v4.netmask=24"]);
case!(d_routes_prefix_24_from_dotted, &["eth0","1.1.1.1","24","","","192.168.2.0","255.255.255.0"], ["routes.to_prefix=24"]);
case!(d_routes_prefix_16, &["eth0","1.1.1.1","24","","","192.168.2.0","255.255.0.0"], ["routes.to_prefix=16"]);
case!(d_routes_prefix_8, &["eth0","1.1.1.1","24","","","192.168.2.0","255.0.0.0"], ["routes.to_prefix=8"]);
case!(d_routes_prefix_25, &["eth0","1.1.1.1","24","","","192.168.2.0","255.255.255.128"], ["routes.to_prefix=25"]);
case!(d_routes_prefix_noncontiguous_16, &["eth0","1.1.1.1","24","","","192.168.2.0","255.0.255.0"], ["routes.to_prefix=16"]);
case!(d_routes_prefix_zero_from_dotted, &["eth0","1.1.1.1","24","","","192.168.2.0","0.0.0.0"], ["routes.to_prefix=0"]);
case!(d_routes_prefix_num_24, &["eth0","1.1.1.1","24","","","192.168.2.0","24"], ["routes.to_prefix=24"]);
case!(d_routes_prefix_num_32, &["eth0","1.1.1.1","24","","","192.168.2.0","32"], ["routes.to_prefix=32"]);
case!(d_routes_prefix_num_0, &["eth0","1.1.1.1","24","","","192.168.2.0","0"], ["routes.to_prefix=0"]);
// 诡异掩码(越界)——记录 mask_to_prefix 实际行为
case!(d_quirk_33_to_2, &["eth0","1.1.1.1","24","","","192.168.2.0","33"], ["routes.to_prefix=2"]);
case!(d_quirk_128_to_1, &["eth0","1.1.1.1","24","","","192.168.2.0","128"], ["routes.to_prefix=1"]);
// 策略掩码也走转换
case!(d_policy_from_prefix_dotted_8, &["eth0","1.1.1.1","24","","","","","","","10.0.0.0","255.0.0.0"], ["policy.rule_from_prefix=8"]);
case!(d_policy_to_prefix_dotted_16, &["eth0","1.1.1.1","24","","","","","","","","","192.168.3.0","255.255.0.0"], ["policy.rule_to_prefix=16"]);

// ============ E. IPv6 地址格式 ============
case!(e1_full_v6, &["eth0","2001:db8:1::10","48"], ["family1_is_v6=true", "v6.addr=2001:db8:1::10", "v6.prefix=48"]);
case!(e2_loopback, &["eth0","::1","128"], ["family1_is_v6=true", "v6.addr=::1", "v6.prefix=128"]);
case!(e3_link_local, &["eth0","fe80::1","64"], ["v6.addr=fe80::1"]);
case!(e4_bare_subnet, &["eth0","2001:db8::","64"], ["v6.addr=2001:db8::"]);
case!(e5_double_colon_only, &["eth0","::","64"], ["family1_is_v6=true", "v6.addr=::"]);

// ============ F. 部分路由 ============
case!(f1_to_tomask_only, &["eth0","1.1.1.1","24","","","192.168.2.0","24"], [
    "routes.to=192.168.2.0", "routes.to_prefix=24", "routes.via=", "routes.table=",
]);
case!(f2_to_via_no_table, &["eth0","1.1.1.1","24","","","192.168.2.0","24","1.1.1.254"], [
    "routes.via=1.1.1.254", "routes.table=",
]);
case!(f3_to_table_skip_via, &["eth0","1.1.1.1","24","","","192.168.2.0","24","","100"], [
    "routes.via=", "routes.table=100",
]);
case!(f4_table_name_string, &["eth0","1.1.1.1","24","","","192.168.2.0","24","1.1.1.254","lan_table"], [
    "routes.table=lan_table",
]);

// ============ G. 部分策略 ============
case!(g1_rule_from_mask, &["eth0","1.1.1.1","24","","","","","","","10.0.0.0","24"], [
    "policy.rule_from=10.0.0.0", "policy.rule_from_prefix=24", "policy.rule_to=", "routes.table=",
]);
case!(g2_rule_from_no_mask, &["eth0","1.1.1.1","24","","","","","","","10.0.0.0"], [
    "policy.rule_from=10.0.0.0", "policy.rule_from_prefix=",
]);
case!(g3_rule_to_mask, &["eth0","1.1.1.1","24","","","","","","","","","192.168.3.0","24"], [
    "policy.rule_to=192.168.3.0", "policy.rule_to_prefix=24", "policy.rule_from=",
]);
case!(g4_rule_to_no_mask, &["eth0","1.1.1.1","24","","","","","","","","","192.168.3.0"], [
    "policy.rule_to=192.168.3.0", "policy.rule_to_prefix=",
]);
case!(g5_policy_without_table, &["eth0","1.1.1.1","24","","","","","","","10.0.0.0"], [
    "policy.rule_from=10.0.0.0", "routes.table=",
]);

// ============ H. mode2(v6)+ IPv4 路由/策略 ============
case!(h1_v6_v4_routes, &["eth0","2001:db8::1","64","fe80::1","","192.168.2.0","24","1.1.1.254","100"], [
    "family1_is_v6=true", "v6.addr=2001:db8::1", "v6.gateway=fe80::1",
    "routes.to=192.168.2.0", "routes.table=100", "v4.present=false",
]);
case!(h2_v6_v4_routes_policy, &["eth0","2001:db8::1","64","fe80::1","","192.168.2.0","24","1.1.1.254","100","10.0.0.0","24","192.168.3.0","24"], [
    "family1_is_v6=true", "routes.to=192.168.2.0", "policy.rule_from=10.0.0.0", "policy.rule_to=192.168.3.0",
]);
case!(h3_v6_two_tokens_second_as_dns, &["eth0","2001:db8::1","64","fe80::1","2001:4860:4860::8888"], [
    "v6.addr=2001:db8::1", "v6.gateway=fe80::1", "v6.dns=2001:4860:4860::8888",
]);

// ============ I. dns1 为 IPv6 形状 → 触发 family2 ============
case!(i1_dns_slot_ipv6_jumps, &["eth0","1.1.1.1","24","1.1.1.254","2001:4860:4860::8888"], [
    "v4.gateway=1.1.1.254", "v4.dns=", "v6.addr=2001:4860:4860::8888",
]);

// ============ J. 边缘/异常输入(解析层)============
case!(j1_empty_net_device, &["","1.2.3.4","24"], ["net_device=", "v4.addr=1.2.3.4"]);
case!(j2_v4_static_no_netmask, &["eth0","1.2.3.4"], ["v4.addr=1.2.3.4", "v4.netmask=", "v4.is_dhcp=false"]);
case!(j3_mask_slot_ipv6_jumps, &["eth0","1.2.3.4","::"], ["v4.addr=1.2.3.4", "v6.addr=::"]);
case!(j4_gateway_dhcp_jumps, &["eth0","1.2.3.4","24","dhcp"], ["v6.addr=dhcp", "v6.is_dhcp=true", "v4.gateway="]);
case!(j5_v4_addr_numeric, &["eth0","24","24"], ["v4.addr=24", "v4.netmask=24"]);

// ============ K. --dry-run / -n 位置 ============
case!(k1_dry_run_front, &["--dry-run","eth0","1.1.1.1","24"], ["v4.addr=1.1.1.1"]);
case!(k2_dry_run_end, &["eth0","1.1.1.1","24","--dry-run"], ["v4.addr=1.1.1.1"]);
case!(k3_n_short, &["eth0","-n","1.1.1.1","24"], ["v4.addr=1.1.1.1"]);
case!(k4_n_end, &["eth0","1.1.1.1","24","-n"], ["v4.addr=1.1.1.1"]);

// ============ L. 错误输入 ============
case_err!(l1_no_args, &[], "missing required argument: net_device");
case_err!(l2_only_net_device, &["eth0"], "missing required argument: ip");
case_err!(l3_dry_run_alone, &["--dry-run"], "missing required argument: net_device");
case_err!(l4_unknown_flag_front, &["--bogus","eth0","1.1.1.1","24"], "invalid option '--bogus'");
case_err!(l5_unknown_flag_end, &["eth0","1.1.1.1","24","--bogus"], "invalid option '--bogus'");
case_err!(l6_empty_ip, &["eth0",""], "missing required argument: ip");

// ============ M. 残留参数告警 ============
case_sub!(m1_trailing_after_family2, &["eth0","1.1.1.1","24","1.1.1.254","8.8.8.8","2001:db8::1","64","fe80::1","2001:db8::dns","EXTRA"], [
    "trailing argument", "v6.dns=2001:db8::dns",
]);
case_sub!(m2_many_trailing, &["eth0","1.1.1.1","24","","","","","","","","","","","","","","junk1","junk2"], [
    "trailing argument",
]);
