use std::env;
use std::fs;
use std::path::Path;

fn main() {
    // 获取项目根目录路径
    let manifest_dir = env::var("CARGO_MANIFEST_DIR").unwrap();
    let git_version_path = Path::new(&manifest_dir).join(".git_version");

    // 读取 .git_version 文件内容
    let git_version = fs::read_to_string(&git_version_path)
        .unwrap_or_else(|_| panic!("Failed to read {:?}", git_version_path))
        .trim()
        .to_string();

    // 将内容设置为编译时环境变量
    println!("cargo:rustc-env=GIT_TAG_COMMIT={}", git_version);
    // 可选：如果文件变化时重新运行 build.rs
    println!("cargo:rerun-if-changed={}", git_version_path.display());
}