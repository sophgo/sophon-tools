//! bm_set_ip 双模式 + 多实例解析器集成测试(通过 --dry-run 驱动)。
//! 覆盖:IP-only 旧模式(向后兼容)/ 4 元组多地址 / 多路由 / 路由+策略 /
//!       多地址+路由+v6 / 策略 to_mask 强制点分 / 异常错误 / flag 位置。
//!
//! 运行:`cargo test --test parse_cases` 或 `bash tests/parse_cases.sh`。

use std::process::Command;

fn dry_run(args: &[&str]) -> String {
    let bin = std::env::var("CARGO_BIN_EXE_bm_set_ip")
        .expect("CARGO_BIN_EXE_bm_set_ip not set; run via `cargo test`");
    let out = Command::new(&bin)
        .arg("--dry-run")
        .args(args)
        .output()
        .unwrap_or_else(|e| panic!("failed to run {}: {}", bin, e));
    let mut s = String::from_utf8_lossy(&out.stdout).into_owned();
    s.push_str(&String::from_utf8_lossy(&out.stderr));
    s
}

fn assert_line(out: &str, expected: &str) {
    assert!(
        out.lines().any(|l| l == expected),
        "expected line {:?}\nfull output:\n{}",
        expected,
        out
    );
}

fn assert_sub(out: &str, expected: &str) {
    assert!(
        out.contains(expected),
        "expected substring {:?}\nfull output:\n{}",
        expected,
        out
    );
}

fn assert_err(args: &[&str], expected: &str) {
    let bin = std::env::var("CARGO_BIN_EXE_bm_set_ip").unwrap();
    let out = Command::new(&bin).arg("--dry-run").args(args).output().unwrap();
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

macro_rules! case {
    ($name:ident, $args:expr, [$($exp:literal),* $(,)?]) => {
        #[test]
        fn $name() {
            let out = dry_run($args);
            $( assert_line(&out, $exp); )*
        }
    };
}
macro_rules! case_sub {
    ($name:ident, $args:expr, [$($exp:literal),* $(,)?]) => {
        #[test]
        fn $name() {
            let out = dry_run($args);
            $( assert_sub(&out, $exp); )*
        }
    };
}
macro_rules! case_err {
    ($name:ident, $args:expr, $exp:literal) => {
        #[test]
        fn $name() {
            assert_err($args, $exp);
        }
    };
}

// ============ A. IP-only 旧模式(向后兼容)============
case!(a1_v4_full, &["eth0","1.1.1.1","24","1.1.1.254","8.8.8.8"], [
    "family1_is_v6=false", "v4.addrs=1.1.1.1/24", "v4.gateway=1.1.1.254", "v4.dns=8.8.8.8",
    "v4.is_dhcp=false", "v6.present=false", "routes.count=0", "policy.present=false",
]);
case!(a2_v4_minimal, &["eth0","1.1.1.1","24"], [
    "v4.addrs=1.1.1.1/24", "v4.gateway=", "v4.dns=", "routes.count=0",
]);
case!(a3_v4_gw_no_dns, &["eth0","1.1.1.1","24","1.1.1.254"], ["v4.gateway=1.1.1.254", "v4.dns="]);
case!(a4_v4_dhcp, &["eth0","dhcp"], ["v4.is_dhcp=true", "v4.addrs=", "v6.present=false"]);
case!(a5_dual_dhcp_old, &["eth0","dhcp","","","","dhcp"], ["v4.is_dhcp=true", "v6.is_dhcp=true", "v6.addrs="]);
case!(a6_v6_only, &["eth0","2001:db8::1","64","fe80::1","2001:4860:4860::8888"], [
    "family1_is_v6=true", "v4.present=false", "v6.addrs=2001:db8::1/64",
    "v6.gateway=fe80::1", "v6.dns=2001:4860:4860::8888",
]);
case!(a7_v4_v6_old, &["eth0","1.1.1.1","24","1.1.1.254","8.8.8.8","2001:db8::1","64","fe80::1"], [
    "v4.addrs=1.1.1.1/24", "v4.dns=8.8.8.8", "v6.addrs=2001:db8::1/64", "v6.gateway=fe80::1",
]);
case!(a8_v4_dotted_mask, &["eth0","1.1.1.1","255.255.255.0"], ["v4.addrs=1.1.1.1/24"]);

// ============ B. 4 元组多地址 ============
case!(b1_multi_addr, &["eth0","1.1.1.1","24","1.1.1.254","8.8.8.8","1.1.1.2","24","",""], [
    "v4.addrs=1.1.1.1/24,1.1.1.2/24", "v4.gateway=1.1.1.254", "routes.count=0",
]);
case!(b2_multi_addr_no_gw, &["eth0","1.1.1.1","24","","","1.1.1.2","24","",""], [
    "v4.addrs=1.1.1.1/24,1.1.1.2/24", "v4.gateway=", "v4.dns=",
]);
case!(b3_multi_addr_dotted, &["eth0","1.1.1.1","255.255.255.0","","","1.1.1.2","255.255.255.0","",""], [
    "v4.addrs=1.1.1.1/24,1.1.1.2/24",
]);

// ============ C. 4 元组多路由 ============
case!(c1_multi_route, &["eth0","1.1.1.1","24","","","192.168.2.0","24","1.1.1.254","100","192.168.3.0","24","1.1.1.254","200"], [
    "routes.count=2", "routes[0].to=192.168.2.0", "routes[0].to_prefix=24",
    "routes[0].via=1.1.1.254", "routes[0].table=100",
    "routes[1].to=192.168.3.0", "routes[1].table=200", "policy.present=false",
]);
case!(c2_route_no_table, &["eth0","1.1.1.1","24","","","192.168.2.0","24","1.1.1.254",""], [
    "routes[0].table=", "routes[0].via=1.1.1.254",
]);
case!(c3_route_table_name, &["eth0","1.1.1.1","24","","","192.168.2.0","24","1.1.1.254","lan_table"], [
    "routes[0].table=lan_table",
]);

// ============ D. 4 元组路由+策略(策略 to_mask 强制点分)============
case!(d1_route_policy, &["eth0","1.1.1.1","24","","","192.168.2.0","24","1.1.1.254","100","10.0.0.0","24","192.168.3.0","255.255.255.0"], [
    "routes.count=1", "routes[0].table=100",
    "policy.present=true", "policy.from=10.0.0.0", "policy.from_prefix=24",
    "policy.to=192.168.3.0", "policy.to_prefix=24", "policy.table=100",
]);
case!(d2_policy_to_mask_dotted8, &["eth0","1.1.1.1","24","","","192.168.2.0","24","1.1.1.254","100","10.0.0.0","255.0.0.0","192.168.3.0","255.255.0.0"], [
    "policy.from_prefix=8", "policy.to_prefix=16",
]);

// ============ E. 多地址 + 路由 + v6(family2 4 元组)============
case!(e1_multi_addr_route_v6, &["eth0","1.1.1.1","24","1.1.1.254","8.8.8.8","1.1.1.2","24","","","192.168.2.0","24","1.1.1.254","100","2001:db8::1","64","fe80::1",""], [
    "v4.addrs=1.1.1.1/24,1.1.1.2/24", "routes.count=1", "routes[0].table=100",
    "v6.addrs=2001:db8::1/64", "v6.gateway=fe80::1", "v6.dns=",
]);
case!(e2_route_then_v6_dhcp, &["eth0","1.1.1.1","24","","","192.168.2.0","24","1.1.1.254","100","dhcp"], [
    "routes.count=1", "v6.is_dhcp=true", "v6.addrs=",
]);

// ============ F. 异常错误 ============
case_err!(f1_no_4tuple_family1, &["eth0","1.1.1.1","24","192.168.2.0","24","1.1.1.254","100"], "incomplete 4-tuple");
case_err!(f2_policy_without_route, &["eth0","1.1.1.1","24","","","10.0.0.0","24","192.168.3.0","255.255.255.0"], "policy requires a preceding route");
case_err!(f3_unclassifiable_pos4, &["eth0","1.1.1.1","24","","","192.168.2.0","24","1.1.1.254","2001:db8::1"], "cannot classify");
case_err!(f4_no_args, &[], "missing required argument: net_device");
case_err!(f5_only_net_device, &["eth0"], "missing required argument: ip");
case_err!(f6_unknown_flag, &["--bogus","eth0","1.1.1.1","24"], "invalid option");
case_err!(f7_extra_addr_not_empty_gw, &["eth0","1.1.1.1","24","1.1.1.254","8.8.8.8","1.1.1.2","24","","8.8.8.8"], "extra address group must be");

// ============ G. 策略 to_mask 前缀数字 → 被当路由(强制点分的代价,记录行为)============
case!(g1_prefix_policy_tomask_read_as_route, &["eth0","1.1.1.1","24","","","192.168.2.0","24","1.1.1.254","100","10.0.0.0","24","192.168.3.0","24"], [
    "routes.count=2", "policy.present=false",
]);

// ============ H. --dry-run / -n 位置 ============
case!(h1_dry_run_front, &["--dry-run","eth0","1.1.1.1","24"], ["v4.addrs=1.1.1.1/24"]);
case!(h2_dry_run_end, &["eth0","1.1.1.1","24","--dry-run"], ["v4.addrs=1.1.1.1/24"]);
case!(h3_n_short, &["eth0","-n","1.1.1.1","24"], ["v4.addrs=1.1.1.1/24"]);
case_sub!(h4_4tuple_dry_run, &["-n","eth0","1.1.1.1","24","","","192.168.2.0","24","1.1.1.254","100"], ["routes.count=1", "routes[0].to=192.168.2.0"]);
