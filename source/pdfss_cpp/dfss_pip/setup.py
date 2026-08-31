#!/usr/bin/env python
# coding: utf-8

from setuptools import setup, find_packages
import os
import shutil
import stat

current_folder = os.path.dirname(os.path.abspath(__file__))
filehandle = open(os.path.join(current_folder,"../git_version"),"r")
version_info = filehandle.readline().rstrip("\n").rstrip("\r")

shutil.copy(os.path.join(current_folder,"../git_version"), os.path.join(current_folder,"dfss/output"))
shutil.copytree(os.path.join(current_folder,"../output"), os.path.join(current_folder,"dfss/output"), dirs_exist_ok=True)

# 打包前对二进制显式赋予执行位：wheel 打包会按文件模式(zip external_attr)保留权限，
# 缺少 x 位会导致 pip 安装后二进制不可执行（Permission denied）
output_dir = os.path.join(current_folder, "dfss", "output")
for binary_name in os.listdir(output_dir):
    if binary_name.startswith("dfss-cpp"):
        binary_path = os.path.join(output_dir, binary_name)
        os.chmod(binary_path, os.stat(binary_path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

setup(
    name='dfss',
    version=version_info,
    author='zetao.zhang',
    author_email='zetao.zhang@sophgo.com',
    description='download_from_sophon_sftp',
    packages=find_packages(),
	package_data={"dfss":["output/*"]},
    include_package_data=True,
)
