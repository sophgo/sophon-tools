#!/usr/bin/python3
# -*- coding: utf-8 -*-
import logging
import argparse
import os
from array import array
import binascii
# from XmlParser import XmlParser
from tempfile import TemporaryDirectory
import shutil

MAX_LOAD_SIZE = 100 * 1024 * 1024
CHUNK_TYPE_DONT_CARE = 0
CHUNK_TYPE_CRC_CHECK = 1
FORMAT = "%(levelname)s: %(message)s"
logging.basicConfig(level=logging.INFO, format=FORMAT)


def parse_Args():
    parser = argparse.ArgumentParser(description="Create CVITEK device image")

    parser.add_argument(
        "file_path",
        metavar="file_path",
        type=str,
        help="the file you want to pack with cvitek image header",
    )
    parser.add_argument(
        "-v", "--verbose", help="increase output verbosity", action="store_true"
    )
    args = parser.parse_args()
    if args.verbose:
        logging.debug("Enable more verbose output")
        logging.getLogger().setLevel(level=logging.DEBUG)

    return args


class ImagerBuilder(object):
    # def __init__(self):
        # self.storage = storage
        # self.file_path = file_path

    def packHeader(self, file_path):
        """
        Header format total 64 bytes
        4 Bytes: Magic
        4 Bytes: Version
        4 Bytes: Chunk header size
        4 Bytes: Total chunks
        4 Bytes: File size
        32 Bytes: Extra Flags
        12 Bytes: Reserved
        """
        with open(file_path, "rb") as fd:
            magic = fd.read(4)
            if magic == b"CIMG":
                logging.debug("%s has been packed, skip it!" % part["file_name"])
                return
            fd.seek(0)
            Magic = array("b", [ord(c) for c in "CIMG"])
            Version = array("I", [1])
            chunk_header_sz = 64
            Chunk_sz = array("I", [chunk_header_sz])
            file_size = os.path.getsize(file_path)
            chunk_counts = file_size // MAX_LOAD_SIZE
            remain = file_size - MAX_LOAD_SIZE * chunk_counts
            if (remain != 0):
                chunk_counts = chunk_counts + 1
            Totak_chunk = array("I", [chunk_counts])
            File_sz = array("I", [file_size + (chunk_counts * chunk_header_sz)])
            # try:
            #     label = part["label"]
            # except KeyError:
            label = "gpt"
            Extra_flags = array("B", [ord(c) for c in label])
            for _ in range(len(label), 32):
                Extra_flags.append(ord("\0"))

            img = open(file_path + ".head", "wb")
            # Write Header
            for h in [Magic, Version, Chunk_sz, Totak_chunk, File_sz, Extra_flags]:
                h.tofile(img)
            img.seek(64)
            total_size = file_size
            offset = 0
            part_sz = 0
            while total_size:
                chunk_sz = min(MAX_LOAD_SIZE, total_size)
                chunk = fd.read(chunk_sz)
                crc = binascii.crc32(chunk) & 0xFFFFFFFF
                chunk_header = self._getChunkHeader(chunk_sz, offset, part_sz, crc)
                img.write(chunk_header)
                img.write(chunk)
                total_size -= chunk_sz
                offset += chunk_sz
            img.close()

    def _getChunkHeader(self, size: int, offset: int, part_sz: int, crc32: int):
        """
        Header format total 64 bytes
        4 Bytes: Chunk Type
        4 Bytes: Chunk data size
        4 Bytes: Program part offset
        4 Bytes: Program part size
        4 Bytes: Crc32 checksum
        """
        logging.info("size:%x, offset:%x, part_sz:%x, crc:%x" % (size, offset, part_sz, crc32))
        Chunk = array(
            "I",
            [
                CHUNK_TYPE_CRC_CHECK,
                size,
                offset,
                part_sz,
                crc32,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
            ],
        )
        return Chunk


def main():
    args = parse_Args()
    # xmlParser = XmlParser(args.xml)
    install_dir = os.path.dirname(args.file_path)
    # parts = xmlParser.parse(install_dir)

    # storage = xmlParser.getStorage()
    # tmp = TemporaryDirectory()
    imgBuilder = ImagerBuilder()

    # for p in parts:
        # Since xml parser will parse with abspath and the user input path can
        # be relative path, use file name to check.
        # if os.path.basename(args.file_path) == p["file_name"]:
        #     if (
        #         storage != "emmc" and storage != "spinor"
        #         and p["file_size"] > p["part_size"] - 128 * 1024
        #         and p["mountpoint"]
        #         and p["mountpoint"] != ""
        #     ):
        #         logging.error(
        #             "Imaege is too big, it will cause mount partition failed!!"
        #         )
        #         raise ValueError

    # tmp_path = os.path.join(tmp.name)
    # out_path = os.path.join(args.output_dir)
    # logging.debug("Moving %s -> %s" % (tmp_path, out_path))
    imgBuilder.packHeader(args.file_path)
    # print("Moving %s" % install_dir)
    # shutil.move(tmp_path, out_path)
    # logging.info("Packing %s done!" % (p["file_name"]))


if __name__ == "__main__":
    main()
