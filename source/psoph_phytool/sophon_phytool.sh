#!/bin/bash
#set -x

usage() {
    echo "usage: $0 <read|write> <ic_name> <device> <phy_addr> <page> <reg_addr> [write_data]"
    echo "examples:"
    echo "read:  $0 read YT eth1 0x0 0xa003 0x1f"
    echo "write: $0 write RTL eth1 0x0 0xd08 0x15 0x19"
}

# 参数校验（在硬件探测之前），避免参数错误时先触发硬件读
if [ "$#" -lt 6 ]; then
    usage
    exit 1
fi

operation=$1
ic_name=$2
device=$3
phy_addr=$4
page=$5
reg_addr=$6

if [ "$operation" != "read" ] && [ "$operation" != "write" ]; then
    echo "[Error]: invalid operation: $operation. choose 'read' or 'write'."
    exit 1
fi

if [ "$operation" == "write" ] && [ "$#" -ne 7 ]; then
    echo "[Warning]: need: <write_data>"
    exit 1
fi

# set page_reg according to ic_name
case "$ic_name" in
    YT)
        page_reg=0x1e
        echo "[info]: ic page reg: $page_reg"
        ;;
    RTL)
        page_reg=0x1f
        echo "[info]: ic page reg: $page_reg"
        ;;
    MARVEL)
        page_reg=0x16
        echo "[info]: ic page reg: $page_reg"
        ;;
    *)
        echo "[Warning]: $ic_name is not support!"
        exit 1
        ;;
esac

# 硬件探测（参数校验通过后进行，按用户指定的 device/phy_addr 读取 PHY ID，不再固定读 eth1）
reg1=$(sudo phytool read ${device}/${phy_addr}/0x02 2>/dev/null)  # PHY ID1
reg2=$(sudo phytool read ${device}/${phy_addr}/0x03 2>/dev/null)  # PHY ID2

if [ -n "$reg1" ] && [ -n "$reg2" ]; then
    reg1_dec=$((reg1))
    reg2_dec=$((reg2))

    combined_dec=$(( (reg1_dec << 16) | reg2_dec ))
    combined_hex=$(printf "0x%08x" $combined_dec)

    echo "[info]: PHY chip ID: $combined_hex"
else
    echo "[Warning]: read PHY ID failed on ${device}/${phy_addr}, device or phy_addr may be wrong."
    echo "[Warning]: you can run 'sudo phytool read ${device}/${phy_addr}/0x02' to check the real error."
    exit 1
fi

function read_phy_reg() {
	device=$1
	phy_addr=$2
	page=$3
	reg_addr=$4

	sudo phytool write ${device}/${phy_addr}/${page_reg} ${page}
	dump_reg=$(sudo phytool read  ${device}/${phy_addr}/${reg_addr})
	echo "[info]: ${device}: page is ${page} , reg addr is ${reg_addr}, reg value is ${dump_reg}"
	sudo phytool write ${device}/${phy_addr}/${page_reg} 0x00
}

function write_phy_reg() {
	device=$1
	phy_addr=$2
	page=$3
	reg_addr=$4
	write_data=$5

	sudo phytool write ${device}/${phy_addr}/${page_reg} ${page}
	if [ $? -ne 0 ]; then
	    echo "[Error]: write page failed: ${device}/${phy_addr}/${page_reg}"
	    exit 1
	fi

	sudo phytool write ${device}/${phy_addr}/${reg_addr} ${write_data}
	if [ $? -ne 0 ]; then
	    echo "[Error]: write reg failed: ${device}/${phy_addr}/${reg_addr}"
	    exit 1
	fi

	sudo phytool write ${device}/${phy_addr}/${page_reg} 0x00
	if [ $? -ne 0 ]; then
	    echo "[Error]: restore page failed: ${device}/${phy_addr}/${page_reg}"
	    exit 1
	fi
}

if [ "$operation" == "read" ]; then
    read_phy_reg $device $phy_addr $page $reg_addr
elif [ "$operation" == "write" ]; then
    write_data=$7
    write_phy_reg $device $phy_addr $page $reg_addr $write_data
    echo "[info]: $device: page: $page, reg addr: $reg_addr, write data: $write_data"
fi
