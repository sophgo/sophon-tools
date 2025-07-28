import os
import platform
import sys

import argparse
import subprocess
import shutil

def get_architecture():
    arch = platform.machine().lower()
    system = platform.system().lower()

    if arch == 'x86_64':
        if system == 'linux':
            return 'linux-amd64'
        elif system == 'windows':
            return 'win-i686.exe'
    if arch == 'amd64':
        if system == 'linux':
            return 'linux-amd64'
        elif system == 'windows':
            return 'win-i686.exe'
    elif arch == 'i686' or arch == 'x86':
        if system == 'windows':
            return 'win-i686.exe'
    elif arch == 'aarch64':
        if system == 'linux':
            return 'linux-arm64'
    elif arch == 'loongarch64':
        if system == 'linux':
            return 'linux-loongarch64'
    elif arch == 'riscv64':
        if system == 'linux':
            return 'linux-riscv64'
    elif arch.startswith('arm'):
        if system == 'linux':
            return 'linux-armbi'
    elif arch == 'sw_64':
        if system == 'linux':
            return 'linux-sw_64'

    return 'unknown'

def get_version_info():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    filehandle = open(os.path.join(script_dir, 'output', 'git_version'),"r")
    version_info = filehandle.readline().rstrip("\n").rstrip("\r")
    return version_info

def get_binary_path(binary_arch: str):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    binary_name = 'dfss-cpp-' + binary_arch
    binary_path = os.path.join(script_dir, 'output', binary_name)
    if not os.path.isfile(binary_path):
        print("Binary file for architecture " + binary_arch + " not found at " + binary_path)
        return None
    return binary_path

def main():
    binary_arch = get_architecture()

    if binary_arch == 'unknown':
        arch = platform.machine().lower()
        system = platform.system().lower()
        print("Unsupported architecture or operating system")
        print("arch:" + arch)
        print("system:" + system)
        return 1
    print("Find architecture: " + binary_arch)

    binary_path = get_binary_path(binary_arch)
    if binary_path is None:
        print("Binary file for architecture " + binary_arch + " not found at " + binary_path)
        return 1
    args = sys.argv[1:]
    try:
        ret = os.system(binary_path + " " + ' '.join(args))
        print("Binary for architecture " + binary_arch + " ret: " + str(ret))
        if ret == 0:
            return 0
        else:
            return 1
    except Exception as e:
        print("Failed to execute binary for architecture " + binary_arch + " : " + str(e))
        return 1

def install_package(package_name: str, extra_args: list) -> int:
    print("Install package: " + package_name)
    supported_packages = ['sail','performance','libsophon'] # TODO(wang.zhang): move supported list to FTP
    if package_name not in supported_packages:
        print("\033[31minstall target '{}' not supported\033[0m".format(package_name))
        return 1
    install_script_name = "get_{}.sh".format(package_name)
    install_script_url = "open@sophgo.com:/dfss_easy_install/{}/{}".format(package_name, install_script_name)

    binary_arch = get_architecture()
    if binary_arch == 'unknown':
        arch = platform.machine().lower()
        system = platform.system().lower()
        print("Unsupported architecture or operating system")
        print("arch:" + arch)
        print("system:" + system)
        return 1
    print("Find architecture: " + binary_arch)
    binary_path = get_binary_path(binary_arch)
    if binary_path is None:
        print("The binary file for architecture " + binary_arch + " is not found")
        return 1

    dfss_home_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    dfss_cache_dir = os.path.join(dfss_home_dir, '.cache')
    original_dir = os.getcwd()
    if not os.path.exists(dfss_cache_dir):
        os.makedirs(dfss_cache_dir)
    os.chdir(dfss_cache_dir)
    try:
        ret = os.system(binary_path + " " + " --url={}".format(install_script_url))
        if ret == 0:
            print("Download script for package {} successfully".format(package_name))
        else:
            print("\033[31mFailed to download script for package {}, ret = {}\033[0m".format(package_name, ret))
            os.chdir(original_dir)
            return 1
    except Exception as e:
        print("Failed to execute binary for architecture " + binary_arch + " : " + str(e))
        os.chdir(original_dir)
        return 1
    # execute package-defined install script
    result = subprocess.run(["bash", install_script_name] + extra_args)
    if (result.returncode != 0):
        print("\033[31mdfss failed to install package {}, ret = {}\033[0m".format(package_name, result.returncode))
        os.chdir(original_dir)
        return 1
    os.chdir(original_dir)
    shutil.rmtree(dfss_cache_dir)
    return 0

if __name__ == '__main__':
    version_info = get_version_info()
    print("dfss python tool, version:", version_info)
    parser = argparse.ArgumentParser(description='dfss python tool, version: {}'.format(version_info), prog='dfss')
    parser.add_argument('--url', help='url to get sftp file')
    parser.add_argument('--user', help='username to login sftp')
    parser.add_argument('--dflag', help='using download flag to get file')
    parser.add_argument('--upflag', help='flag of need upload file, need upfile')
    parser.add_argument('--upfile', help='need to upload file, need upflag')
    parser.add_argument('--enable_http', action='store_true', help='url or dfss get file by http enable')
    parser.add_argument('--connect_timeout', help='config timeout on http connect')
    parser.add_argument('--debug', action='store_true', help='open debug info print mode')
    parser.add_argument('--no_json', action='store_true', help='do not use json config')
    parser.add_argument('--force_server', help='force specify a server link')
    parser.add_argument('--list', action='store_true', help='list server info')

    parser.add_argument('--install', help='install package')

    args, parse_known_args = parser.parse_known_args()
    if args.install is None:
        ret = main()
        exit(ret)
    else:
        ret = install_package(args.install, parse_known_args)
        if ret != 0:
            print("\033[31mFailed to install package: " + args.install + "\033[0m")
            exit(1)
        exit(0)