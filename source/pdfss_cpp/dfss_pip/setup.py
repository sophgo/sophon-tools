#!/usr/bin/env python
# coding: utf-8

from setuptools import setup, find_packages
import os
import shutil

current_folder = os.path.dirname(os.path.abspath(__file__))
filehandle = open(os.path.join(current_folder,"../git_version"),"r")
version_info = filehandle.readline().rstrip("\n").rstrip("\r")
shutil.copy(os.path.join(current_folder,"../git_version"), os.path.join(current_folder,"dfss/output"))

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
