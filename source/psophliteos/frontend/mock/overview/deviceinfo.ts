import { MockMethod } from 'vite-plugin-mock';
import { resultSuccess } from '../_util';

const deviceInfo = {
  deviceSn: 'HQDZKMNBBJEBH0250', //设备序列号
  deviceName: '', //设备名称
  deviceType: 'se6', //设备类型
  sdkVersion: '2.7.0', //sdk版本
  buildTime: '220809_095905', //版本信息
  wanIp: '172.28.8.71', //wanIP
  lanIp: '172.16.140.200,172.16.150.200', //lanIP
  operatingSystem: 'Ubuntu 20.04 LTS', //操作系统版本
  runTime: '0:44:46', //运行时间
  deviceIp: '172.28.8.71', //控制板IP

  ipList: ['172.28.8.71', '172.16.140.200', '172.16.150.200'], //ip列表

  cpu: {
    cores: 8, //控制板cpu核心数
    frequency: 2300, //控制板cpu主频
    usage: 2, //控制板cpu使用率
  },

  memory: {
    total: 11973, //控制板总内存
    usage: 1, //控制板内存使用率
  },

  disk: [
    {
      id: 'mmcblk0',
      total: 28755, //控制板磁盘总容量
      usage: 1, //控制板磁盘使用率
    },
  ],

  netCard: [
    {
      ip: '172.28.8.71', //控制板网卡ip
      bandwidth: 1000, //控制板网卡带宽
      mac: 'e0:a5:09:00:88:3d', //控制板网卡mac地址
      netIn: 1001608247, //控制板网卡流入KB
      netOut: 23094178, //控制板网卡流出KB
    },
    {
      ip: '172.16.140.200', //控制板网卡ip
      bandwidth: 1000, //控制板网卡带宽
      mac: 'e0:a5:09:00:89:94', //控制板网卡mac地址
      netIn: 189933456, //控制板网卡流入KB
      netOut: 4713218867, //控制板网卡流出KB
    },
    {
      ip: '172.16.150.200', //控制板网卡ip
      bandwidth: 1000, //控制板网卡带宽
      mac: 'e0:a5:09:00:89:95', //控制板网卡mac地址
      netIn: 189930368, //控制板网卡流入KB
      netOut: 4712344907, //控制板网卡流出KB
    },
  ],

  coreComputingUnit: {
    board: [
      {
        boardSn: 'HQDZKMNBBJEBH0001', //核心板设备编码
        boardType: 'se6', //核心板类型
        temperature: 53, //芯片温度
        fanSpeed: 0, //核心板风扇转速
        cpu: {
          cores: 8, //核心数
          frequency: 2300, //控制板cpu主频
          usage: 1, //控制板cpu使用率
        }, //控制板cpu
        memory: {
          total: 3862, //控制板总内存
          usage: 1, //控制板cpu使用率
        }, //控制板内存
        disk: [
          {
            id: 'mmcblk0',
            total: 28755, //控制板总内存
            usage: 1, //控制板cpu使用率
          },
        ], //控制板内存
        netCard: [
          {
            ip: '172.16.150.13', //控制板网卡IP
            bandwidth: 1000, //控制板网卡带宽
            mac: 'e0:a5:09:00:8a:f0', //控制板网卡mac地址
            netIn: 555534, //控制板网卡流入KB
            netOut: 326836, //控制板网卡流出KB
          },
        ], //控制板网卡
        chip: [
          {
            slot: '',
            chipSn: 'N/A', //芯片序列号
            health: 0, //芯片状态(0 表示健康、 1 表示故障)
            temperature: 56, //芯片温度
            memoryUsedBytes: 0, //芯片内存使用率
            memoryTotalBytes: 7983, //芯片内存
            chipTemperatureCelsius: 0,
            tpuUtililizationRate: 0, //芯片tpu使用率
            theoretialCalculationCapacity: 17.6,
            deploys: [], //应用数组
          },
        ], //芯片数组
      },
      {
        boardSn: 'HQDZKMNBBJEBH0002', //核心板设备编码
        boardType: 'se6', //核心板类型
        temperature: 53, //芯片温度
        fanSpeed: 0, //核心板风扇转速
        cpu: {
          cores: 8, //核心数
          frequency: 2300, //控制板cpu主频
          usage: 1, //控制板cpu使用率
        }, //控制板cpu
        memory: {
          total: 3862, //控制板总内存
          usage: 1, //控制板cpu使用率
        }, //控制板内存
        disk: [
          {
            id: 'mmcblk0',
            total: 28755, //控制板总内存
            usage: 1, //控制板cpu使用率
          },
        ], //控制板内存
        netCard: [
          {
            ip: '172.16.150.13', //控制板网卡IP
            bandwidth: 1000, //控制板网卡带宽
            mac: 'e0:a5:09:00:8a:f0', //控制板网卡mac地址
            netIn: 555534, //控制板网卡流入KB
            netOut: 326836, //控制板网卡流出KB
          },
        ], //控制板网卡
        chip: [
          {
            slot: '',
            chipSn: 'N/A', //芯片序列号
            health: 0, //芯片状态(0 表示健康、 1 表示故障)
            temperature: 56, //芯片温度
            memoryUsedBytes: 0, //芯片内存使用率
            memoryTotalBytes: 7983, //芯片内存
            chipTemperatureCelsius: 0,
            tpuUtililizationRate: 0, //芯片tpu使用率
            theoretialCalculationCapacity: 17.6,
            deploys: [], //应用数组
          },
        ], //芯片数组
      },
      {
        boardSn: 'HQDZKMNBBJEBH0003', //核心板设备编码
        boardType: 'se6', //核心板类型
        temperature: 53, //芯片温度
        fanSpeed: 0, //核心板风扇转速
        cpu: {
          cores: 8, //核心数
          frequency: 2300, //控制板cpu主频
          usage: 1, //控制板cpu使用率
        }, //控制板cpu
        memory: {
          total: 3862, //控制板总内存
          usage: 1, //控制板cpu使用率
        }, //控制板内存
        disk: [
          {
            id: 'mmcblk0',
            total: 28755, //控制板总内存
            usage: 1, //控制板cpu使用率
          },
        ], //控制板内存
        netCard: [
          {
            ip: '172.16.150.13', //控制板网卡IP
            bandwidth: 1000, //控制板网卡带宽
            mac: 'e0:a5:09:00:8a:f0', //控制板网卡mac地址
            netIn: 555534, //控制板网卡流入KB
            netOut: 326836, //控制板网卡流出KB
          },
        ], //控制板网卡
        chip: [
          {
            slot: '',
            chipSn: 'N/A', //芯片序列号
            health: 0, //芯片状态(0 表示健康、 1 表示故障)
            temperature: 56, //芯片温度
            memoryUsedBytes: 0, //芯片内存使用率
            memoryTotalBytes: 7983, //芯片内存
            chipTemperatureCelsius: 0,
            tpuUtililizationRate: 0, //芯片tpu使用率
            theoretialCalculationCapacity: 17.6,
            deploys: [], //应用数组
          },
        ], //芯片数组
      },
      {
        boardSn: 'HQDZKMNBBJEBH0004', //核心板设备编码
        boardType: 'se6', //核心板类型
        temperature: 53, //芯片温度
        fanSpeed: 0, //核心板风扇转速
        cpu: {
          cores: 8, //核心数
          frequency: 2300, //控制板cpu主频
          usage: 1, //控制板cpu使用率
        }, //控制板cpu
        memory: {
          total: 3862, //控制板总内存
          usage: 1, //控制板cpu使用率
        }, //控制板内存
        disk: [
          {
            id: 'mmcblk0',
            total: 28755, //控制板总内存
            usage: 1, //控制板cpu使用率
          },
        ], //控制板内存
        netCard: [
          {
            ip: '172.16.150.13', //控制板网卡IP
            bandwidth: 1000, //控制板网卡带宽
            mac: 'e0:a5:09:00:8a:f0', //控制板网卡mac地址
            netIn: 555534, //控制板网卡流入KB
            netOut: 326836, //控制板网卡流出KB
          },
        ], //控制板网卡
        chip: [
          {
            slot: '',
            chipSn: 'N/A', //芯片序列号
            health: 0, //芯片状态(0 表示健康、 1 表示故障)
            temperature: 56, //芯片温度
            memoryUsedBytes: 0, //芯片内存使用率
            memoryTotalBytes: 7983, //芯片内存
            chipTemperatureCelsius: 0,
            tpuUtililizationRate: 0, //芯片tpu使用率
            theoretialCalculationCapacity: 17.6,
            deploys: [], //应用数组
          },
        ], //芯片数组
      },
      {
        boardSn: 'HQDZKMNBBJEBH0005', //核心板设备编码
        boardType: 'se6', //核心板类型
        temperature: 53, //芯片温度
        fanSpeed: 0, //核心板风扇转速
        cpu: {
          cores: 8, //核心数
          frequency: 2300, //控制板cpu主频
          usage: 1, //控制板cpu使用率
        }, //控制板cpu
        memory: {
          total: 3862, //控制板总内存
          usage: 1, //控制板cpu使用率
        }, //控制板内存
        disk: [
          {
            id: 'mmcblk0',
            total: 28755, //控制板总内存
            usage: 1, //控制板cpu使用率
          },
        ], //控制板内存
        netCard: [
          {
            ip: '172.16.150.13', //控制板网卡IP
            bandwidth: 1000, //控制板网卡带宽
            mac: 'e0:a5:09:00:8a:f0', //控制板网卡mac地址
            netIn: 555534, //控制板网卡流入KB
            netOut: 326836, //控制板网卡流出KB
          },
        ], //控制板网卡
        chip: [
          {
            slot: '',
            chipSn: 'N/A', //芯片序列号
            health: 0, //芯片状态(0 表示健康、 1 表示故障)
            temperature: 56, //芯片温度
            memoryUsedBytes: 0, //芯片内存使用率
            memoryTotalBytes: 7983, //芯片内存
            chipTemperatureCelsius: 0,
            tpuUtililizationRate: 0, //芯片tpu使用率
            theoretialCalculationCapacity: 17.6,
            deploys: [], //应用数组
          },
        ], //芯片数组
      },
      {
        boardSn: 'HQDZKMNBBJEBH0006', //核心板设备编码
        boardType: 'se6', //核心板类型
        temperature: 53, //芯片温度
        fanSpeed: 0, //核心板风扇转速
        cpu: {
          cores: 8, //核心数
          frequency: 2300, //控制板cpu主频
          usage: 1, //控制板cpu使用率
        }, //控制板cpu
        memory: {
          total: 3862, //控制板总内存
          usage: 1, //控制板cpu使用率
        }, //控制板内存
        disk: [
          {
            id: 'mmcblk0',
            total: 28755, //控制板总内存
            usage: 1, //控制板cpu使用率
          },
        ], //控制板内存
        netCard: [
          {
            ip: '172.16.150.13', //控制板网卡IP
            bandwidth: 1000, //控制板网卡带宽
            mac: 'e0:a5:09:00:8a:f0', //控制板网卡mac地址
            netIn: 555534, //控制板网卡流入KB
            netOut: 326836, //控制板网卡流出KB
          },
        ], //控制板网卡
        chip: [
          {
            slot: '',
            chipSn: 'N/A', //芯片序列号
            health: 0, //芯片状态(0 表示健康、 1 表示故障)
            temperature: 56, //芯片温度
            memoryUsedBytes: 0, //芯片内存使用率
            memoryTotalBytes: 7983, //芯片内存
            chipTemperatureCelsius: 0,
            tpuUtililizationRate: 0, //芯片tpu使用率
            theoretialCalculationCapacity: 17.6,
            deploys: [], //应用数组
          },
        ], //芯片数组
      },
      {
        boardSn: 'HQDZKMNBBJEBH0007', //核心板设备编码
        boardType: 'se6', //核心板类型
        temperature: 53, //芯片温度
        fanSpeed: 0, //核心板风扇转速
        cpu: {
          cores: 8, //核心数
          frequency: 2300, //控制板cpu主频
          usage: 1, //控制板cpu使用率
        }, //控制板cpu
        memory: {
          total: 3862, //控制板总内存
          usage: 1, //控制板cpu使用率
        }, //控制板内存
        disk: [
          {
            id: 'mmcblk0',
            total: 28755, //控制板总内存
            usage: 1, //控制板cpu使用率
          },
        ], //控制板内存
        netCard: [
          {
            ip: '172.16.150.13', //控制板网卡IP
            bandwidth: 1000, //控制板网卡带宽
            mac: 'e0:a5:09:00:8a:f0', //控制板网卡mac地址
            netIn: 555534, //控制板网卡流入KB
            netOut: 326836, //控制板网卡流出KB
          },
        ], //控制板网卡
        chip: [
          {
            slot: '',
            chipSn: 'N/A', //芯片序列号
            health: 0, //芯片状态(0 表示健康、 1 表示故障)
            temperature: 56, //芯片温度
            memoryUsedBytes: 0, //芯片内存使用率
            memoryTotalBytes: 7983, //芯片内存
            chipTemperatureCelsius: 0,
            tpuUtililizationRate: 0, //芯片tpu使用率
            theoretialCalculationCapacity: 17.6,
            deploys: [], //应用数组
          },
        ], //芯片数组
      },
      {
        boardSn: 'HQDZKMNBBJEBH0008', //核心板设备编码
        boardType: 'se6', //核心板类型
        temperature: 53, //芯片温度
        fanSpeed: 0, //核心板风扇转速
        cpu: {
          cores: 8, //核心数
          frequency: 2300, //控制板cpu主频
          usage: 1, //控制板cpu使用率
        }, //控制板cpu
        memory: {
          total: 3862, //控制板总内存
          usage: 1, //控制板cpu使用率
        }, //控制板内存
        disk: [
          {
            id: 'mmcblk0',
            total: 28755, //控制板总内存
            usage: 1, //控制板cpu使用率
          },
        ], //控制板内存
        netCard: [
          {
            ip: '172.16.150.13', //控制板网卡IP
            bandwidth: 1000, //控制板网卡带宽
            mac: 'e0:a5:09:00:8a:f0', //控制板网卡mac地址
            netIn: 555534, //控制板网卡流入KB
            netOut: 326836, //控制板网卡流出KB
          },
        ], //控制板网卡
        chip: [
          {
            slot: '',
            chipSn: 'N/A', //芯片序列号
            health: 0, //芯片状态(0 表示健康、 1 表示故障)
            temperature: 56, //芯片温度
            memoryUsedBytes: 0, //芯片内存使用率
            memoryTotalBytes: 7983, //芯片内存
            chipTemperatureCelsius: 0,
            tpuUtililizationRate: 0, //芯片tpu使用率
            theoretialCalculationCapacity: 17.6,
            deploys: [], //应用数组
          },
        ], //芯片数组
      },
      {
        boardSn: 'HQDZKMNBBJEBH0009', //核心板设备编码
        boardType: 'se6', //核心板类型
        temperature: 53, //芯片温度
        fanSpeed: 0, //核心板风扇转速
        cpu: {
          cores: 8, //核心数
          frequency: 2300, //控制板cpu主频
          usage: 1, //控制板cpu使用率
        }, //控制板cpu
        memory: {
          total: 3862, //控制板总内存
          usage: 1, //控制板cpu使用率
        }, //控制板内存
        disk: [
          {
            id: 'mmcblk0',
            total: 28755, //控制板总内存
            usage: 1, //控制板cpu使用率
          },
        ], //控制板内存
        netCard: [
          {
            ip: '172.16.150.13', //控制板网卡IP
            bandwidth: 1000, //控制板网卡带宽
            mac: 'e0:a5:09:00:8a:f0', //控制板网卡mac地址
            netIn: 555534, //控制板网卡流入KB
            netOut: 326836, //控制板网卡流出KB
          },
        ], //控制板网卡
        chip: [
          {
            slot: '',
            chipSn: 'N/A', //芯片序列号
            health: 0, //芯片状态(0 表示健康、 1 表示故障)
            temperature: 56, //芯片温度
            memoryUsedBytes: 0, //芯片内存使用率
            memoryTotalBytes: 7983, //芯片内存
            chipTemperatureCelsius: 0,
            tpuUtililizationRate: 0, //芯片tpu使用率
            theoretialCalculationCapacity: 17.6,
            deploys: [], //应用数组
          },
        ], //芯片数组
      },
      {
        boardSn: 'HQDZKMNBBJEBH0010', //核心板设备编码
        boardType: 'se6', //核心板类型
        temperature: 53, //芯片温度
        fanSpeed: 0, //核心板风扇转速
        cpu: {
          cores: 8, //核心数
          frequency: 2300, //控制板cpu主频
          usage: 1, //控制板cpu使用率
        }, //控制板cpu
        memory: {
          total: 3862, //控制板总内存
          usage: 1, //控制板cpu使用率
        }, //控制板内存
        disk: [
          {
            id: 'mmcblk0',
            total: 28755, //控制板总内存
            usage: 1, //控制板cpu使用率
          },
        ], //控制板内存
        netCard: [
          {
            ip: '172.16.150.13', //控制板网卡IP
            bandwidth: 1000, //控制板网卡带宽
            mac: 'e0:a5:09:00:8a:f0', //控制板网卡mac地址
            netIn: 555534, //控制板网卡流入KB
            netOut: 326836, //控制板网卡流出KB
          },
        ], //控制板网卡
        chip: [
          {
            slot: '',
            chipSn: 'N/A', //芯片序列号
            health: 0, //芯片状态(0 表示健康、 1 表示故障)
            temperature: 56, //芯片温度
            memoryUsedBytes: 0, //芯片内存使用率
            memoryTotalBytes: 7983, //芯片内存
            chipTemperatureCelsius: 0,
            tpuUtililizationRate: 0, //芯片tpu使用率
            theoretialCalculationCapacity: 17.6,
            deploys: [], //应用数组
          },
        ], //芯片数组
      },
      {
        boardSn: 'HQDZKMNBBJEBH0011', //核心板设备编码
        boardType: 'se6', //核心板类型
        temperature: 53, //芯片温度
        fanSpeed: 0, //核心板风扇转速
        cpu: {
          cores: 8, //核心数
          frequency: 2300, //控制板cpu主频
          usage: 1, //控制板cpu使用率
        }, //控制板cpu
        memory: {
          total: 3862, //控制板总内存
          usage: 1, //控制板cpu使用率
        }, //控制板内存
        disk: [
          {
            id: 'mmcblk0',
            total: 28755, //控制板总内存
            usage: 1, //控制板cpu使用率
          },
        ], //控制板内存
        netCard: [
          {
            ip: '172.16.150.13', //控制板网卡IP
            bandwidth: 1000, //控制板网卡带宽
            mac: 'e0:a5:09:00:8a:f0', //控制板网卡mac地址
            netIn: 555534, //控制板网卡流入KB
            netOut: 326836, //控制板网卡流出KB
          },
        ], //控制板网卡
        chip: [
          {
            slot: '',
            chipSn: 'N/A', //芯片序列号
            health: 0, //芯片状态(0 表示健康、 1 表示故障)
            temperature: 56, //芯片温度
            memoryUsedBytes: 0, //芯片内存使用率
            memoryTotalBytes: 7983, //芯片内存
            chipTemperatureCelsius: 0,
            tpuUtililizationRate: 0, //芯片tpu使用率
            theoretialCalculationCapacity: 17.6,
            deploys: [], //应用数组
          },
        ], //芯片数组
      },
      {
        boardSn: 'HQDZKMNBBJEBH0012', //核心板设备编码
        boardType: 'se6', //核心板类型
        temperature: 53, //芯片温度
        fanSpeed: 0, //核心板风扇转速
        cpu: {
          cores: 8, //核心数
          frequency: 2300, //控制板cpu主频
          usage: 1, //控制板cpu使用率
        }, //控制板cpu
        memory: {
          total: 3862, //控制板总内存
          usage: 1, //控制板cpu使用率
        }, //控制板内存
        disk: [
          {
            id: 'mmcblk0',
            total: 28755, //控制板总内存
            usage: 1, //控制板cpu使用率
          },
        ], //控制板内存
        netCard: [
          {
            ip: '172.16.150.13', //控制板网卡IP
            bandwidth: 1000, //控制板网卡带宽
            mac: 'e0:a5:09:00:8a:f0', //控制板网卡mac地址
            netIn: 555534, //控制板网卡流入KB
            netOut: 326836, //控制板网卡流出KB
          },
        ], //控制板网卡
        chip: [
          {
            slot: '',
            chipSn: 'N/A', //芯片序列号
            health: 0, //芯片状态(0 表示健康、 1 表示故障)
            temperature: 56, //芯片温度
            memoryUsedBytes: 0, //芯片内存使用率
            memoryTotalBytes: 7983, //芯片内存
            chipTemperatureCelsius: 0,
            tpuUtililizationRate: 0, //芯片tpu使用率
            theoretialCalculationCapacity: 17.6,
            deploys: [], //应用数组
          },
        ], //芯片数组
      },
    ],
  },
};
export default [
  {
    url: '/api/device/resource',
    statusCode: 200,
    method: 'get',
    response: () => {
      return resultSuccess(deviceInfo);
    },
  },
] as MockMethod[];
