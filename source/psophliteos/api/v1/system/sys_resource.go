package system

import (
	"fmt"
	"math"
	"net/http"
	"os/exec"
	"sort"
	"strconv"
	"strings"

	"sophliteos/client/ssm"
	"sophliteos/global"
	"sophliteos/logger"
	mvc "sophliteos/mvc/core"
	"sophliteos/mvc/i18n"
	"sophliteos/mvc/types"

	"github.com/gin-gonic/gin"
	"github.com/mitchellh/mapstructure"
)

type ResourceApi struct{}

func (b *ResourceApi) NewResource(c *gin.Context) {
	resource := GetArmResource(c)
	c.JSON(http.StatusOK, mvc.Success(resource))
}

func GetDeviceType(devType string) string {
	deviceType := strings.ToUpper(devType)

	if strings.Contains(deviceType, "SE5") {
		deviceType = "SE5"
	} else if strings.Contains(deviceType, "SE6") {
		deviceType = "SE6"
	} else if strings.Contains(deviceType, "SE7") || deviceType == "BM1684X EVB" {
		deviceType = "SE7"
	} else if strings.Contains(deviceType, "SE8") {
		deviceType = "SE8"
	} else if strings.Contains(deviceType, "SE9") {
		deviceType = "SE9"
	} else {
		deviceType = GetSysDeviceType()
	}

	return deviceType
}

func GetArmResource(c *gin.Context) types.Resource {

	ctrlResource, err := ssm.GetCtrlResource()
	if err != nil {
		logger.Error("error is :%v", err)
		logger.Error("ctrlResource is :%v", ctrlResource)
	}
	// mvc.HandleError(err)

	ctrlBasic, deviceSn, err := ssm.GetCtrlBasic()
	// mvc.HandleError(err)
	if err != nil {
		logger.Error("error is :%v", err)
		logger.Error("ctrlBasic is :%v", ctrlBasic)
	}

	deviceType := GetDeviceType(ctrlBasic.Configure.Basic.DeviceType)
	global.DeviceType = deviceType

	var emmcDiskCapacity = getDiskCapacity(ctrlResource.CentralProcessingUnit.Disk, true)
	var diskCapacity = getDiskCapacity(ctrlResource.CentralProcessingUnit.Disk, false)

	global.SSmLists.CoreSsm = []types.SsmVersion{}
	resource := types.Resource{
		DeviceSn:        deviceSn,
		CtrlBoardSn:     ctrlBasic.ChipSn,
		DeviceName:      ctrlBasic.Configure.Basic.DeviceName,
		DeviceType:      deviceType,
		SdkVersion:      ctrlBasic.System.SdkVersion,
		OperatingSystem: ctrlBasic.System.OperatingSystem,
		RunTime:         ctrlBasic.System.Runtime,
		BuildTime:       ctrlBasic.System.BuildTime,
		BmssmVersion:    ctrlBasic.System.BmssmVersion,
		IPList:          ctrlBasic.IpList,
		Cpu:             getCpu(ctrlResource.CentralProcessingUnit.Cpu),
		Memory:          getMemory(ctrlResource.CentralProcessingUnit.Memory),
		Disk:            getDisks(ctrlResource.CentralProcessingUnit.Disk),
		NetCard:         getNetCarts(ctrlResource.CentralProcessingUnit.NetCard),
		Int8Count: types.ResourceCount{
			Unit: "TOPS",
		},
		Fp16Count: types.ResourceCount{
			Unit: "TFLOPS",
		},
		Fp32Count: types.ResourceCount{
			Unit: "TFLOPS",
		},
		CpuCount: types.ResourceCount{
			Available: ctrlResource.CentralProcessingUnit.Cpu.Cores,
			Total:     ctrlResource.CentralProcessingUnit.Cpu.Cores,
			Unit:      "核",
			Desc:      fmt.Sprintf("@%dMHz", ctrlResource.CentralProcessingUnit.Cpu.Frequency),
		},
		MemoryCount: types.ResourceCount{
			Available: ctrlResource.CentralProcessingUnit.Memory.Available,
			Total:     ctrlResource.CentralProcessingUnit.Memory.Total,
			Unit:      "GB",
			Desc:      "LPDDR4x",
		},
		EMMCCount: types.ResourceCount{
			Available: emmcDiskCapacity,
			Total:     emmcDiskCapacity,
			Unit:      "GB",
		},
		DiskCount: types.ResourceCount{
			Available: diskCapacity,
			Total:     diskCapacity,
			Unit:      "GB",
		},
	}
	if strings.EqualFold(mvc.GetLang(c.Request), i18n.En) {
		resource.CpuCount.Unit = "cores"
	}

	var boards []types.Board

	for _, board := range ctrlResource.CoreComputingUnit.Board {
		cpu := getCpu(board.CoreSys.Cpu)
		memory := getMemory(board.CoreSys.Mem)
		disk := getDisks(board.CoreSys.Disks)
		netCart := getNetCarts(board.CoreSys.NetCards)
		var chips []types.Chip
		coreSys := board.CoreSys

		resource.MemoryCount.Available += coreSys.Mem.Available
		resource.MemoryCount.Total += coreSys.Mem.Total

		chipIndex, _ := strconv.Atoi(board.Chip[0].ChipIndex)

		sv := types.SsmVersion{
			ChipIndex: chipIndex,
			DeviceSn:  board.BoardSn,
			Ip:        board.BoardHost,
			Version:   "V" + coreSys.BmssmVersion + "-" + coreSys.BuildTime,
		}
		global.SSmLists.CoreSsm = append(global.SSmLists.CoreSsm, sv)

		for _, chip := range board.Chip {
			chips = append(chips, types.Chip{
				ChipIndex:                     chipIndex,
				Health:                        chip.Health,
				Temperature:                   chip.Temperature,
				MemoryUsedBytes:               int64(coreSys.Mem.Total - coreSys.Mem.Available),
				MemoryTotalBytes:              int64(coreSys.Mem.Total),
				TpuUtililizationRate:          chip.UtilizationRate,
				TheoretialCalculationCapacity: chip.CalculationCapacity,
				Deploys:                       []types.Deploy{},
			})
			chip.CalculationCapacityInt8 = chip.CalculationCapacity
			if chip.Health == 0 { // 正常
				resource.Int8Count.Health++
				resource.Int8Count.Available += chip.CalculationCapacityInt8

				resource.Fp16Count.Health++
				resource.Fp16Count.Available += chip.CalculationCapacityFp16

				resource.Fp32Count.Health++
				resource.Fp32Count.Available += chip.CalculationCapacityFp32

				resource.CpuCount.Health++
				resource.CpuCount.Available += cpu.Cores

				resource.MemoryCount.Health++
				resource.MemoryCount.Available += chip.Memory.Available
				resource.MemoryCount.Total += chip.Memory.Total

				resource.DiskCount.Health++
				resource.DiskCount.Available += getDiskCapacity(coreSys.Disks, false)

				resource.EMMCCount.Health++
				resource.EMMCCount.Available += getDiskCapacity(coreSys.Disks, true)
			} else {
				resource.Int8Count.UnHealth++
				resource.Fp16Count.UnHealth++
				resource.Fp32Count.UnHealth++
				resource.CpuCount.UnHealth++
				resource.MemoryCount.UnHealth++
				resource.DiskCount.UnHealth++
			}
			resource.Int8Count.Total += chip.CalculationCapacityInt8
			resource.Fp16Count.Total += chip.CalculationCapacityFp16
			resource.Fp32Count.Total += chip.CalculationCapacityFp32
			resource.CpuCount.Total += cpu.Cores

			resource.Fp32Count.Total = resource.Int8Count.Total / 8
			resource.Fp16Count.Total = resource.Int8Count.Total / 4

			resource.DiskCount.Total += getDiskCapacity(coreSys.Disks, false)
			resource.EMMCCount.Total += getDiskCapacity(coreSys.Disks, true)

		}
		if len(board.Chip) == 0 {
			logger.Error("无法读取核心版芯片信息 SN=%s", board.BoardSn)
			continue
		}
		boards = append(boards, types.Board{
			Cpu:         cpu,
			Memory:      memory,
			Disk:        disk,
			NetCard:     netCart,
			Number:      chipIndex,
			BoardSn:     board.BoardSn,
			BoardType:   board.BoardType,
			Temperature: board.Temperature,
			FanSpeed:    board.FanspeedPercent,
			SdkVersion:  board.SdkVersion,
			Chip:        chips,
		})
	}

	resource.MemoryCount.Available = resource.MemoryCount.Available / 1024
	resource.MemoryCount.Total = resource.MemoryCount.Total / 1024
	resource.CoreComputingUnit = types.CoreComputingUnit{
		Board: boards,
	}

	if deviceType == "SE5" || deviceType == "SE7" || deviceType == "SE9" {
		if len(ctrlBasic.IpList) > 0 {
			resource.DeviceIP = ctrlBasic.IpList[0].IP
			resource.WanIP = resource.DeviceIP
			if len(ctrlBasic.IpList) > 1 {
				resource.LanIP = ctrlBasic.IpList[1].IP
			}
		}
		global.SSmLists.CoreSsm = []types.SsmVersion{}
	} else if deviceType == "SE6" || deviceType == "SE8" {
		wanIp := ""
		lanIp := ""
		for _, nt := range ctrlResource.CentralProcessingUnit.NetCard {
			if strings.HasPrefix(nt.NetCardName, "enp") {
				if nt.IP != "" {
					wanIp = nt.IP
				}
			} else if strings.HasPrefix(nt.NetCardName, "eth") {
				lanIp = lanIp + "," + nt.IP
			}
		}
		resource.DeviceIP = wanIp
		resource.WanIP = wanIp
		resource.LanIP = lanIp
		if len(lanIp) > 1 {
			resource.LanIP = lanIp[1:]
		}
	}

	sort.Slice(global.SSmLists.CoreSsm, func(i, j int) bool {
		return global.SSmLists.CoreSsm[i].ChipIndex < global.SSmLists.CoreSsm[j].ChipIndex
	})

	global.SSmLists.CtrlSsm.DeviceSn = ctrlResource.DeviceSn
	global.SSmLists.CtrlSsm.Ip = resource.DeviceIP
	global.SSmLists.CtrlSsm.Version = "V" + ctrlResource.CentralProcessingUnit.BmssmVersion + "-" + ctrlResource.CentralProcessingUnit.BuildTime
	global.SdkVersion = ctrlBasic.System.SdkVersion
	// 兼容3wan口se6
	result, _ := ssm.GetIP()
	var se6Ips []ssm.Ip
	err = mapstructure.Decode(result.Result, &se6Ips)
	mvc.HandleError(err)
	// ssm未返回，兼容添加网卡
	appendNetCard(se6Ips, resource.NetCard)

	if len(ctrlResource.CoreComputingUnit.Board) > 0 && len(ctrlResource.CoreComputingUnit.Board[0].Chip) > 0 {
		chipType := ctrlResource.CoreComputingUnit.Board[0].Chip[0].ChipType //1-1684; 2-1684X; 3-1688
		switch chipType {
		case 1:
			resource.TpuMax = "16"
		case 2:
			resource.TpuMax = "32"
		case 3:
			resource.TpuMax = "16"
		default:
			resource.TpuMax = "0"
		}
	}

	logger.Debug("resource is :%v", resource)
	global.Resource = resource
	return resource
}

func (b *ResourceApi) Test(c *gin.Context) {
	c.JSON(http.StatusOK, mvc.Success(nil))
}

func appendNetCard(ips []ssm.Ip, netCards []types.NetCard) {
	for _, ip := range ips {
		if containsNetCard(netCards, ip.NetCardName) {
			continue
		}
		netCards = append(netCards, types.NetCard{
			Ip:        ip.IP,
			Name:      ip.Name,
			Bandwidth: ip.Bandwidth,
			Mac:       ip.Mac,
			NetIn:     ip.NetRx,
			NetOut:    ip.NetTx,
		})
	}
}

func containsNetCard(netCards []types.NetCard, name string) bool {
	for _, item := range netCards {
		if item.Name == name {
			return true
		}
	}
	return false
}

func getCpu(cpu ssm.CPU) types.CPU {
	return types.CPU{
		Cores:     cpu.Cores,
		Frequency: cpu.Frequency,
		Usage:     cpu.UtilizationRate,
		Type:      cpu.Type,
		Arch:      cpu.Arch,
	}
}

func getMemory(memory ssm.Memory) types.Memory {
	if memory.Total == 0 {
		return types.Memory{
			Total: 0,
			Usage: 0,
		}
	}
	return types.Memory{
		Total: memory.Total,
		Usage: 100 - (memory.Available/memory.Total)*100,
	}
}

func getDisks(disk []ssm.Disk) []types.Disk {
	var disks []types.Disk

	free, total := addDisk(disk, true)
	if math.Abs(total) < 0.1 {
		total = 1
		free = 0
	}
	disks = append(disks, types.Disk{
		ID:    "mmcblk",
		Total: total,
		Usage: (1 - float64(free/total)) * 100,
	})

	free, total = addDisk(disk, false)
	if math.Abs(total) < 0.1 {
		total = 1
		free = 0
	}
	disks = append(disks, types.Disk{
		ID:    "others",
		Total: total,
		Usage: (1 - float64(free/total)) * 100,
	})
	return disks
}

func addDisk(disk []ssm.Disk, eMMC bool) (float64, float64) {
	free := 0.0
	total := 0.0

	for _, _disk := range disk {
		if _disk.Total < 1 {
			continue
		}
		if eMMC && strings.HasPrefix(_disk.DiskName, "/dev/mmc") {
			total = total + _disk.Total
			free += _disk.Free
		} else if !eMMC && !strings.HasPrefix(_disk.DiskName, "/dev/mmc") {
			total += _disk.Total
			free += _disk.Free
		}
	}
	return free, total
}

func getDiskCapacity(disk []ssm.Disk, eMMC bool) float64 {
	var capacity float64
	for _, _disk := range disk {
		if _disk.Total == 0 {
			continue
		}
		if eMMC && strings.HasPrefix(_disk.DiskName, "/dev/mmc") {
			capacity += _disk.Total
		} else if !eMMC && !strings.HasPrefix(_disk.DiskName, "/dev/mmc") {
			capacity += _disk.Total
		}
	}
	return capacity / 1024
}

func getNetCarts(netCards []ssm.NetCard) []types.NetCard {
	var res []types.NetCard
	for _, netCard := range netCards {
		if !strings.HasPrefix(netCard.NetCardName, "en") && !strings.HasPrefix(netCard.NetCardName, "eth") {
			continue
		}
		res = append(res, types.NetCard{
			Ip:        netCard.IP,
			Name:      netCard.NetCardName,
			Bandwidth: netCard.Bandwidth,
			Mac:       netCard.Mac,
			NetIn:     netCard.NetRx,
			NetOut:    netCard.NetTx,
		})
	}
	return res
}

func getCtrlSn() string {
	if global.DeviceType != "SE6" && global.DeviceType != "SE8" {
		return ""
	}
	cmd := exec.Command("bash", "bm_get_basic_info")
	output, err := cmd.CombinedOutput()
	if err != nil {
		logger.Error("执行命令bm_get_basic_info发生错误:", err)
		return ""
	}

	var chipSN string
	lines := strings.Split(string(output), "\n")
	for _, line := range lines {
		if strings.HasPrefix(line, "chip sn:") {
			chipSN = strings.TrimSpace(strings.TrimPrefix(line, "chip sn:"))
			break // 找到chip sn后可以退出循环
		}
	}
	return chipSN
}
