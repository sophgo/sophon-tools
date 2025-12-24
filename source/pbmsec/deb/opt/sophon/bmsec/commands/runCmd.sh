#!/bin/bash
###############################################
############zetao.zhang@sophgo.com#############
###############################################

# 该命令执行后可以通过seNCtrl_RUN_LOG环境变量获取各个算力核心的log
unset seNCtrl_RUN_LOG
declare -A seNCtrl_RUN_LOG
unset seNCtrl_RUN_SHMID
declare -A seNCtrl_RUN_SHMID
seNCtrl_cleanup() {
    echo -e "\nReceived a kill signal. Cleaning up..."
    for key in "${!seNCtrl_RUN_SHMID[@]}"; do
        ipcrm -m "${seNCtrl_RUN_SHMID[$key]}" &> /dev/null
    done
    exit 0
}
trap seNCtrl_cleanup SIGTERM SIGINT
userInputSubId=""
userInputCmd=""
seNCtrl_ALL_SUB_RUNS=()
seNCtrl_RET_INFO=()
seNCtrl_RUN_PID=()
if [ $# -eq 2 ]; then
    userInputSubId="$1"
    userInputCmd="$2"
else
    echo "Enter the core id for run cmd, default is all:"
    read userInputSubId
    if [ -z "$userInputSubId" ]; then
        userInputSubId="all"
    fi
    echo "Enter the cmd:"
    read userInputCmd
fi
if [[ "$userInputSubId" =~ ^[0-9]+(\+[0-9]+)+$ ]]; then
  IFS=$seNCtrl_MULTIPLE_SEPARATOR read -ra seNCtrl_ALL_SUB_RUNS <<< "$userInputSubId"
  userInputSubId=all
fi
echo "Core Id: $userInputSubId, Cmd: $userInputCmd"
if [ "$userInputSubId" == "all" ]; then
    temp_shm_id_info=$(ipcmk -M $((1024 * 1024 * 1)) -p 0777)
    temp_shm_id=$(echo "$temp_shm_id_info" | grep -oP '\d+')
    for ((i = 0; i < $seNCtrl_ALL_SUB_NUM; i++)); do
        if [[ "${seNCtrl_ALL_SUB_IP[$i]}" == "NAN" ]]; then continue; fi
        if [ ${#seNCtrl_ALL_SUB_RUNS[@]} -gt 0 ] && [[ ! " ${seNCtrl_ALL_SUB_RUNS[*]} " =~ " $(($i+1)) " ]]; then continue; fi
        export SSHPASS=${seNCtrl_ALL_SUB_PASSWORD[$i]}
        output=$(ipcmk -M $((1024 * 1024 * 1)) -p 0777)
        shmid=$(echo "$output" | grep -oP '\d+')
        seNCtrl_RUN_SHMID[$i]=$shmid
        ssh-keygen -R ${seNCtrl_ALL_SUB_IP[$i]} &> /dev/null
        (runOutput=$(${seNCtrl_SSH_CMD} ${seNCtrl_ALL_SUB_USER[$i]}@${seNCtrl_ALL_SUB_IP[$i]} -p ${seNCtrl_ALL_SUB_PORT[$i]} "${userInputCmd}"); (if [ $? -eq "0" ]; then echo "[BMSEC]:Core $(($i+1)) Return Sucess"; else echo "[BMSEC]:Core $(($i+1)) Return Error"; fi; echo "$runOutput") | $seNCtrl_MEMSHARE $shmid w) &
        seNCtrl_RUN_PID+=("$!")
        unset SSHPASS
    done
    ipcrm -m "${temp_shm_id}"
    for element in "${seNCtrl_RUN_PID[@]}"
    do
        wait -n "$element"
    done
    for ((i = 0; i < $seNCtrl_ALL_SUB_NUM; i++)); do
        if [[ "${seNCtrl_ALL_SUB_IP[$i]}" == "NAN" ]]; then continue; fi
        if [ ${#seNCtrl_ALL_SUB_RUNS[@]} -gt 0 ] && [[ ! " ${seNCtrl_ALL_SUB_RUNS[*]} " =~ " $(($i+1)) " ]]; then continue; fi
        output=$($seNCtrl_MEMSHARE ${seNCtrl_RUN_SHMID[$i]} r)
        seNCtrl_RUN_LOG[$i]="$(echo "$output" | tail -n +2)"
        seNCtrl_RET_INFO[${#seNCtrl_RET_INFO[@]}]="$(echo "$output" | head -n 1)"
        ipcrm -m ${seNCtrl_RUN_SHMID[$i]}
        unset seNCtrl_RUN_SHMID[$i]
        echo "********core $(($i + 1)) run log************"
        echo "${seNCtrl_RUN_LOG[$i]}"
    done
    for item in "${seNCtrl_RET_INFO[@]}"; do
        echo "${item}"
    done
elif [[ "$userInputSubId" =~ ^[0-9]+$ &&  userInputSubId -ge 1 &&  userInputSubId -le $seNCtrl_ALL_SUB_NUM ]]; then
    userInputSubIds=$(($userInputSubId - 1))
    if [[ "${seNCtrl_ALL_SUB_IP[$(($userInputSubId - 1))]}" == "NAN" ]]; then echo "cannot support core Id:$userInputSubId"; return 0; fi
    export SSHPASS=${seNCtrl_ALL_SUB_PASSWORD[$userInputSubIds]}
    ssh-keygen -R ${seNCtrl_ALL_SUB_IP[$userInputSubIds]} &> /dev/null
    ${seNCtrl_SSH_CMD} ${seNCtrl_ALL_SUB_USER[$userInputSubIds]}@${seNCtrl_ALL_SUB_IP[$userInputSubIds]} -p ${seNCtrl_ALL_SUB_PORT[$userInputSubIds]} "${userInputCmd}"
    if [ $? -ne 0 ]; then echo "command "${FUNCNAME[1]}" "${BASH_SOURCE[1]}" "$LINENO" error"; return 1; fi
    unset SSHPASS
else
    echo "error arg:  $userInputSubId"
fi
