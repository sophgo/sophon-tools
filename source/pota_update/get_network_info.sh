#!/bin/bash

# 网络配置信息获取并生成bm_set_ip命令脚本，仅支持IPv4
# 支持systemd-networkd、NetworkManager和netplan

# 最终会把网络配置命令写入到这个文件
BM_SET_IP_BASH_FILE="./set_network_config_by_bm_set_ip_autogen.sh"

# 颜色定义
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 要检查的网口列表
INTERFACES=("eth0" "eth1")

# 存储配置信息的数组
declare -A CONFIG_IFACE
declare -A CONFIG_DHCP
declare -A CONFIG_IP
declare -A CONFIG_NETMASK
declare -A CONFIG_GATEWAY
declare -A CONFIG_DNS

# 函数：检测网络管理器类型
detect_network_manager() {
    if systemctl is-active --quiet NetworkManager 2>/dev/null; then
        echo "NetworkManager"
    elif systemctl is-active --quiet systemd-networkd 2>/dev/null; then
        echo "systemd-networkd"
    elif [ -d "/etc/netplan/" ] && ls /etc/netplan/*.yaml 2>/dev/null | grep -q .; then
        echo "netplan"
    else
        echo "unknown"
    fi
}

# 函数：从CIDR格式中提取IP和掩码
parse_cidr() {
    local cidr=$1
    if [[ $cidr == *"/"* ]]; then
        local ip=$(echo "$cidr" | cut -d'/' -f1)
        local prefix=$(echo "$cidr" | cut -d'/' -f2)

        # 将前缀长度转换为点分十进制掩码
        local mask=""
        if [[ $prefix =~ ^[0-9]+$ ]] && [ "$prefix" -ge 0 ] && [ "$prefix" -le 32 ]; then
            local full_octets=$((prefix / 8))
            local remainder=$((prefix % 8))
            local mask_octets=()

            for ((i=0; i<4; i++)); do
                if [ $i -lt $full_octets ]; then
                    mask_octets+=("255")
                elif [ $i -eq $full_octets ] && [ $remainder -gt 0 ]; then
                    local octet=$((256 - 2**(8 - remainder)))
                    mask_octets+=("$octet")
                else
                    mask_octets+=("0")
                fi
            done

            mask=$(IFS=.; echo "${mask_octets[*]}")
        else
            mask=$prefix  # 如果不是数字前缀，直接使用
        fi

        echo "$ip $mask"
    else
        echo "$cidr"
    fi
}

# 函数：查找systemd-networkd配置文件
find_systemd_network_config() {
    local iface=$1

    local config_paths=(
        "/run/systemd/network/10-netplan-${iface}.network"
        "/etc/systemd/network/10-netplan-${iface}.network"
        "/run/systemd/network/*${iface}*.network"
        "/etc/systemd/network/*${iface}*.network"
        "/lib/systemd/network/*${iface}*.network"
    )

    for path in "${config_paths[@]}"; do
        if ls $path 2>/dev/null | grep -q "\.network$"; then
            echo $(ls $path 2>/dev/null | head -1)
            return 0
        fi
    done

    return 1
}

# 函数：查找NetworkManager连接配置
find_nm_connection_config() {
    local iface=$1

    local nm_paths=(
        "/etc/NetworkManager/system-connections/"
        "/run/NetworkManager/system-connections/"
        "/var/lib/NetworkManager/"
    )

    for path in "${nm_paths[@]}"; do
        if [ -d "$path" ]; then
            local conn_file=$(find "$path" -name "*.nmconnection" -o -name "*.conf" 2>/dev/null | \
                xargs grep -l "interface-name=$iface\$\|id=.*$iface.*" 2>/dev/null | head -1)

            if [ -n "$conn_file" ]; then
                echo "$conn_file"
                return 0
            fi
        fi
    done

    return 1
}

# 函数：从systemd-networkd配置文件中获取配置
get_config_from_systemd() {
    local config_file=$1
    local iface=$2

    if [ ! -f "$config_file" ]; then
        return 1
    fi

    # 解析DHCP配置
    if grep -q "DHCP=yes" "$config_file" || grep -q "DHCP=ipv4" "$config_file"; then
        CONFIG_DHCP[$iface]="dhcp"
    elif grep -q "DHCP=no" "$config_file" || grep -q "Address=" "$config_file"; then
        CONFIG_DHCP[$iface]="static"
    fi

    # 解析IP地址和掩码
    local address=$(grep "Address=" "$config_file" | sed 's/Address=//g' | head -1)
    if [ -n "$address" ]; then
        local parsed=$(parse_cidr "$address")
        if [[ $parsed == *" "* ]]; then
            CONFIG_IP[$iface]=$(echo "$parsed" | awk '{print $1}')
            CONFIG_NETMASK[$iface]=$(echo "$parsed" | awk '{print $2}')
        else
            CONFIG_IP[$iface]=$parsed
        fi
    fi

    # 解析网关
    CONFIG_GATEWAY[$iface]=$(grep "Gateway=" "$config_file" | sed 's/Gateway=//g' | head -1)

    # 解析DNS服务器（最多保留一个DNS）
    CONFIG_DNS[$iface]=$(grep "DNS=" "$config_file" | sed 's/DNS=//g' | head -1 | awk '{print $1}')
}

# 函数：从NetworkManager配置文件中获取配置
get_config_from_nm() {
    local config_file=$1
    local iface=$2

    if [ ! -f "$config_file" ]; then
        return 1
    fi

    # 解析IPv4配置
    local ipv4_method=$(grep -E "^method=|^\[ipv4\]" -A 1 "$config_file" 2>/dev/null | \
        grep "method=" | cut -d= -f2 | head -1)

    # 判断是否动态
    if [ "$ipv4_method" = "auto" ] || [ "$ipv4_method" = "dhcp" ]; then
        CONFIG_DHCP[$iface]="dhcp"
    elif [ "$ipv4_method" = "manual" ]; then
        CONFIG_DHCP[$iface]="static"
    fi

    # 解析IP地址和掩码
    if [ "${CONFIG_DHCP[$iface]}" = "static" ]; then
        local address_info=$(grep -A 10 "^\[ipv4\]" "$config_file" 2>/dev/null | \
            grep "address1=" | cut -d= -f2 | head -1)

        if [ -z "$address_info" ]; then
            address_info=$(grep -A 10 "^\[ipv4\]" "$config_file" 2>/dev/null | \
                grep "addresses=" | cut -d= -f2 | head -1)
        fi

        if [ -n "$address_info" ]; then
            # 处理格式 "IP/掩码 网关"
            local address_part=$(echo "$address_info" | awk -F',' '{print $1}')
            local parsed=$(parse_cidr "$address_part")
            if [[ $parsed == *" "* ]]; then
                CONFIG_IP[$iface]=$(echo "$parsed" | awk '{print $1}')
                CONFIG_NETMASK[$iface]=$(echo "$parsed" | awk '{print $2}')
            else
                CONFIG_IP[$iface]=$parsed
            fi

            # 提取网关（如果存在）
            CONFIG_GATEWAY[$iface]=$(echo "$address_info" | awk -F',' '{print $2}')
        fi
    fi

    # 解析DNS服务器
    CONFIG_DNS[$iface]=$(grep -A 10 "^\[ipv4\]" "$config_file" 2>/dev/null | \
        grep "dns=" | cut -d'=' -f2 | cut -d',' -f1 | cut -d';' -f1 | head -1)
}

# 函数：从netplan yaml配置中获取配置
# 参数1：网卡名；参数2（可选）：yaml文件路径（测试用），缺省取 /etc/netplan/ 下
# 第一个包含该网卡的 yaml。systemd-networkd 渲染出的 .network 文件在部分系统上
# 权限为 root:systemd-network 0640（如 CV84X2 真机 Ubuntu 22.04 rootfs），非 root
# 用户不可读，此时回退解析 world-readable 的 netplan 源 yaml。
get_config_from_netplan() {
    local iface=$1
    local yaml_file=${2:-}

    # 网卡名仅允许安全字符，防止拼进 awk 动态正则
    [[ "$iface" =~ ^[A-Za-z0-9._-]+$ ]] || return 1

    if [ -z "$yaml_file" ]; then
        for f in /etc/netplan/*.yaml; do
            [ -r "$f" ] || continue
            if grep -qE "^[[:space:]]+${iface}[[:space:]]*:" "$f" 2>/dev/null; then
                yaml_file=$f
                break
            fi
        done
    fi
    [ -n "$yaml_file" ] && [ -r "$yaml_file" ] || return 1

    # 提取 iface 键下缩进更深的所有行（直到同级或更浅缩进的下一个键）
    local block
    block=$(awk -v iface="$iface" '
        !found && $0 ~ ("^[[:space:]]+" iface "[[:space:]]*:") {
            found=1; match($0, /^[[:space:]]*/); ind=RLENGTH; next
        }
        found {
            match($0, /^[[:space:]]*/); cur=RLENGTH
            if (cur <= ind) exit
            print
        }' "$yaml_file")
    [ -n "$block" ] || return 1

    # 解析dhcp4（netplan 布尔：yes/no/true/false）
    if echo "$block" | grep -qE "^[[:space:]]*dhcp4:[[:space:]]*(yes|true)[[:space:]]*$"; then
        CONFIG_DHCP[$iface]="dhcp"
    fi

    # 解析addresses（inline 列表或多行列表），取第一个地址
    local address=""
    address=$(echo "$block" | grep -E "^[[:space:]]*addresses:" | head -1 | \
sed 's/^[[:space:]]*addresses:[[:space:]]*//')
    if [[ "$address" == "["* ]]; then
        # inline 列表：addresses: [a/24, b/24]
        address=$(echo "$address" | tr -d '[]' | awk -F',' '{print $1}' | tr -d ' ')
    elif [ -z "$address" ]; then
        # 多行列表：取其后第一个 "- ip/prefix" 行
        address=$(echo "$block" | grep -E "^[[:space:]]*-[[:space:]]*[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+/" | \
head -1 | sed 's/^[[:space:]]*-[[:space:]]*//')
    fi
    if [ -n "$address" ] && [[ "$address" == *"/"* ]]; then
        local parsed=$(parse_cidr "$address")
        if [[ $parsed == *" "* ]]; then
            CONFIG_IP[$iface]=$(echo "$parsed" | awk '{print $1}')
            CONFIG_NETMASK[$iface]=$(echo "$parsed" | awk '{print $2}')
        else
            CONFIG_IP[$iface]=$parsed
        fi
        # 无 dhcp4 行但配置了地址时按静态处理（与 systemd 解析器语义一致）
        if [ -z "${CONFIG_DHCP[$iface]}" ]; then
            CONFIG_DHCP[$iface]="static"
        fi
    fi

    # 解析网关（legacy gateway4；路由式 routes: to: default 不在范例支持范围）
    CONFIG_GATEWAY[$iface]=$(echo "$block" | grep -E "^[[:space:]]*gateway4:" | head -1 | \
sed 's/^[[:space:]]*gateway4:[[:space:]]*//')

    # 解析DNS服务器（最多保留一个DNS，与 #133 修复保持一致）
    CONFIG_DNS[$iface]=$(echo "$block" | grep -A 5 -E "^[[:space:]]*nameservers:" | \
grep -E "^[[:space:]]*addresses:" | head -1 | \
sed 's/^[[:space:]]*addresses:[[:space:]]*//' | tr -d '[]' | \
awk -F',' '{print $1}' | tr -d ' ')
    if [ -z "${CONFIG_DNS[$iface]}" ]; then
        # 多行列表：取 nameservers 块内第一个 "- ip" 条目（netplan 常见格式）
        CONFIG_DNS[$iface]=$(echo "$block" | grep -A 5 -E "^[[:space:]]*nameservers:" | \
grep -E "^[[:space:]]*-[[:space:]]*[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+" | head -1 | \
sed 's/^[[:space:]]*-[[:space:]]*//')
    fi
}

# 函数：获取网口配置信息
get_interface_config() {
    local iface=$1

    echo -e "\n${BLUE}=== 获取 $iface 配置信息 ===${NC}"

    # 检测网络管理器
    local manager=$(detect_network_manager)
    echo -e "${YELLOW}网络管理器：${NC}$manager"

    # 根据网络管理器类型查找配置文件
    local config_file=""

    case $manager in
        "systemd-networkd")
            config_file=$(find_systemd_network_config "$iface")
            if [ -n "$config_file" ]; then
                if [ -r "$config_file" ]; then
                    echo -e "${YELLOW}配置文件：${NC}$config_file"
                    get_config_from_systemd "$config_file" "$iface"
                else
                    echo -e "${YELLOW}配置文件：${NC}$config_file（无读权限，回退解析 netplan yaml）"
                    get_config_from_netplan "$iface"
                fi
            else
                # 找不到 .network 文件时同样回退 netplan 源 yaml
                get_config_from_netplan "$iface"
            fi
            ;;
        "NetworkManager")
            config_file=$(find_nm_connection_config "$iface")
            if [ -n "$config_file" ]; then
                echo -e "${YELLOW}配置文件：${NC}$config_file"
                get_config_from_nm "$config_file" "$iface"
            fi
            ;;
        "netplan")
            get_config_from_netplan "$iface"
            ;;
    esac

    # 如果没找到配置，设置默认值
    if [ -z "${CONFIG_DHCP[$iface]}" ]; then
        CONFIG_DHCP[$iface]="unknown"
    fi

    # 显示获取的配置
    echo -e "${GREEN}网口：${NC}$iface"
    echo -e "${GREEN}是否动态：${NC}${CONFIG_DHCP[$iface]}"
    echo -e "${GREEN}IP：${NC}${CONFIG_IP[$iface]:-未配置}"
    echo -e "${GREEN}掩码：${NC}${CONFIG_NETMASK[$iface]:-未配置}"
    echo -e "${GREEN}网关：${NC}${CONFIG_GATEWAY[$iface]:-未配置}"
    echo -e "${GREEN}DNS：${NC}${CONFIG_DNS[$iface]:-未配置}"
}

# 函数：生成bm_set_ip命令
generate_bm_set_ip_command() {
    local iface=$1

    echo -e "\n${YELLOW}=== 生成 $iface 的 bm_set_ip 命令 ===${NC}"

    # 检查是否有有效配置
    if [ "${CONFIG_DHCP[$iface]}" = "unknown" ] || [ -z "${CONFIG_DHCP[$iface]}" ]; then
        echo -e "${RED}错误：未找到 $iface 的有效配置${NC}"
        return 1
    fi

    # 构建命令
    local cmd="bm_set_ip $iface"

    if [ "${CONFIG_DHCP[$iface]}" = "dhcp" ]; then
        # DHCP配置
        cmd="bm_set_ip_auto $iface"
        echo -e "${GREEN}DHCP IPv4 配置命令：${NC}"
        echo "$cmd"

    elif [ "${CONFIG_DHCP[$iface]}" = "static" ]; then
        # 静态配置
        if [ -z "${CONFIG_IP[$iface]}" ] || [ -z "${CONFIG_NETMASK[$iface]}" ]; then
            echo -e "${RED}错误：静态配置缺少IP或掩码${NC}"
            return 1
        fi

        cmd="$cmd '${CONFIG_IP[$iface]}' '${CONFIG_NETMASK[$iface]}'"

        # 添加网关（如果存在）
        if [ -n "${CONFIG_GATEWAY[$iface]}" ]; then
            cmd="$cmd '${CONFIG_GATEWAY[$iface]}'"
        else
            cmd="$cmd ''"
        fi

        # 添加DNS（如果存在）
        if [ -n "${CONFIG_DNS[$iface]}" ]; then
            cmd="$cmd '${CONFIG_DNS[$iface]}'"
        else
            cmd="$cmd ''"
        fi

        echo -e "${GREEN}静态 IPv4 配置命令：${NC}"
        echo "$cmd"
    fi
    echo "$cmd" >> ${BM_SET_IP_BASH_FILE}

}

# 主程序
main() {
    echo -e "${BLUE}网络配置信息获取${NC}"
    echo -e "${BLUE}生成bm_set_ip命令并写入${BM_SET_IP_BASH_FILE}${NC}"
    echo -e "${BLUE}====================================${NC}"

    echo "#!/bin/bash" > ${BM_SET_IP_BASH_FILE}
    echo "" >> ${BM_SET_IP_BASH_FILE}
    # 获取每个网口的配置
    for iface in "${INTERFACES[@]}"; do
        get_interface_config "$iface"
        generate_bm_set_ip_command "$iface"
    done

    echo ""
    echo -e "${BLUE}=== 网络配置脚本内容 ===${NC}"
    cat ${BM_SET_IP_BASH_FILE}
}

# 执行主程序
main
