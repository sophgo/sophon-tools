// @ts-nocheck
import { defineStore } from 'pinia';
import { store } from '/@/store';
import { resourceApi, basicApi } from '/@/api/overview/index';
import { useI18n } from '/@/hooks/web/useI18n';
import { asyncRoutes } from '/@/router/routes';
import { usePermissionStore } from '/@/store/modules/permission';

const permissionStore = usePermissionStore();
const { t } = useI18n();
// interface DeviceState {
//   deviceInfo: object;
//   cpu: Array<number>;
//   memory: Array<number>;
//   chipTemperature: Array<number>;
//   fanSpeed: Array<number>;
// }
enum deviceRunningSatus {
  'running' = 0,
  'error' = 1,
}

export const useDeviceInfo = defineStore({
  id: 'app-device-info',
  state: () => ({
    singleBoardArr: ['se5', 'se7', 'se9'],
    deviceInfo: {
      deviceName: '',
      deviceSn: '',
      deviceType: '',
      deviceIp: '',
      operatingSystem: '',
      lanIp: '',
      wanIp: '',
      // 数字秒数；避免初始值为字符串导致 setInterval 做 ' '+1 字符串拼接
      runTime: 0,
      sdkVersion: '',
      bmssmVersion: '',
      status: 'running',
      temperature: 0,
      fanSpeed: 0,
      int8Count: {},
      fp16Count: {},
      fp32Count: {},
      cpuCount: {},
      memoryCount: {},
      eMMCCount: {},
      diskCount: {},
    },
    cpu: [],
    memory: [],
    tpu: [],
    chipTemperature: [],
    fanSpeed: [],
    deviceStatus: [], // 设备运行状态
    originData: {} as any, // 设备原始数据
  }),
  getters: {
    deviceType: (state) => state.deviceInfo.deviceType,
    // 判断是否为单板
    isSingleBoard: (state) => {
      return state.singleBoardArr.some((item) =>
        state.deviceInfo.deviceType.toLocaleLowerCase().includes(item),
      );
    },
  },
  actions: {
    async getDeviceInfo() {
      // ssm 反代后直接返回 bmssm 契约：
      //   resource = []CtrlResource，取 [0]，顶层只有 deviceSn/deviceType/centralProcessingUnit/coreComputingUnit
      //   basic    = { chipSn, configure.basic{deviceName,deviceType}, ipList[], system{operatingSystem,runtime,bmssmVersion,buildTime,sdkVersion} }
      // 原 sophliteos 后端 sys_resource.go 把 centralProcessingUnit.{cpu,memory,disk,netCard} 提到顶层、
      // 并合并 basic 的 deviceName/sdkVersion/operatingSystem/runTime/bmssmVersion/ctrlBoardSn/ipList。
      // 这里在前端做同样的归一化，让 detail*.vue 直接读 originData.* 即可。
      const [raw, basic] = await Promise.all([
        resourceApi().catch(() => null),
        basicApi().catch(() => null),
      ]);
      const result = Array.isArray(raw) ? raw[0] : raw;

      if (result) {
        // centralProcessingUnit 字段提到顶层（视图读 originData.cpu/memory/disk/netCard）
        const cpu = result.centralProcessingUnit || {};
        if (cpu.cpu && result.cpu === undefined) result.cpu = cpu.cpu;
        if (cpu.memory && result.memory === undefined) result.memory = cpu.memory;
        if (cpu.disk && result.disk === undefined) result.disk = cpu.disk;
        if (cpu.netCard && result.netCard === undefined) result.netCard = cpu.netCard;
        if (result.bmssmVersion === undefined && cpu.bmssmVersion !== undefined)
          result.bmssmVersion = cpu.bmssmVersion;
        if (result.buildTime === undefined && cpu.buildTime !== undefined)
          result.buildTime = cpu.buildTime;

        // basic 补 deviceName/sdkVersion/operatingSystem/runTime/bmssmVersion/ctrlBoardSn/ipList
        if (basic) {
          const sys = basic.system || {};
          const cfgBasic = basic.configure?.basic || {};
          if (cfgBasic.deviceName !== undefined && result.deviceName === undefined)
            result.deviceName = cfgBasic.deviceName;
          if (sys.sdkVersion !== undefined && result.sdkVersion === undefined)
            result.sdkVersion = sys.sdkVersion;
          if (sys.operatingSystem !== undefined && result.operatingSystem === undefined)
            result.operatingSystem = sys.operatingSystem;
          if (sys.runtime !== undefined && result.runTime === undefined)
            result.runTime = sys.runtime;
          if (sys.bmssmVersion !== undefined && result.bmssmVersion === undefined)
            result.bmssmVersion = sys.bmssmVersion;
          if (sys.buildTime !== undefined && result.buildTime === undefined)
            result.buildTime = sys.buildTime;
          if (basic.chipSn && result.ctrlBoardSn === undefined)
            result.ctrlBoardSn = basic.chipSn;
          if (basic.ipList && result.ipList === undefined) result.ipList = basic.ipList;
        }

        this.originData = result;
        const { cpu: cpuInfo, memory, coreComputingUnit, deviceSn, deviceType } = result;
        Object.keys(this.deviceInfo).forEach((key) => {
          // runTime: 守卫，格式 "hh:mm:ss" 才解析
          if (key === 'runTime') {
            const rt = result[key];
            if (typeof rt === 'string' && rt.includes(':')) {
              const s = rt.split(':');
              if (s.length >= 3) {
                this.deviceInfo[key] = s[0] * 60 * 60 + s[1] * 60 + +s[2];
              }
            }
          } else if (key === 'deviceIp') {
            // 优先 ipList，否则取第一张有 IP 的网卡
            this.deviceInfo[key] =
              result.ipList?.[0]?.ip ||
              result.netCard?.find((c) => c.ip)?.ip ||
              result.ip ||
              '';
          } else if (key === 'wanIp') {
            this.deviceInfo[key] = result.netCard?.find((c) => c.ip)?.ip || '';
          } else if (key === 'lanIp') {
            const cards = result.netCard || [];
            const primary = cards.find((c) => c.ip);
            this.deviceInfo[key] = cards
              .filter((c) => c.ip && c !== primary)
              .map((c) => c.ip)
              .join(',');
          } else if (key === 'int8Count') {
            const chip = result?.coreComputingUnit?.board?.[0]?.chip?.[0];
            this.deviceInfo[key] = {
              total: chip?.calculationCapacityInt8 ?? 0,
              unit: 'TOPS',
              desc: 'INT8',
            };
          } else if (key === 'fp16Count') {
            const chip = result?.coreComputingUnit?.board?.[0]?.chip?.[0];
            this.deviceInfo[key] = {
              total: chip?.calculationCapacityFp16 ?? 0,
              unit: 'TOPS',
              desc: 'FP16',
            };
          } else if (key === 'fp32Count') {
            const chip = result?.coreComputingUnit?.board?.[0]?.chip?.[0];
            this.deviceInfo[key] = {
              total: chip?.calculationCapacityFp32 ?? 0,
              unit: 'TOPS',
              desc: 'FP32',
            };
          } else if (key === 'cpuCount') {
            this.deviceInfo[key] = { total: cpuInfo?.cores ?? 0, desc: cpuInfo?.type ?? '' };
          } else if (key === 'memoryCount') {
            this.deviceInfo[key] = { total: memory?.total ?? 0, unit: 'MB' };
          } else if (key === 'eMMCCount') {
            // emmc 仅计 /opt 挂载的 mmcblk0p 分区
            const disks = result.disk || [];
            this.deviceInfo[key] = {
              total: disks
                .filter(
                  (d) =>
                    /mmcblk0p\d+/.test(d.diskName || '') && d.mountOn === '/opt',
                )
                .reduce((s, d) => s + (d.total || 0), 0),
              unit: 'MB',
            };
          } else if (key === 'diskCount') {
            // emmc 整体：筛 /dev/mmcblk0* 分区求和
            const disks = (result.disk || []).filter((d) =>
              (d.diskName || '').startsWith('/dev/mmcblk0'),
            );
            const total = disks.reduce((s, d) => s + (d.total || 0), 0);
            const used = disks.reduce(
              (s, d) => s + ((d.total || 0) - (d.free ?? (d.total || 0))),
              0,
            );
            this.deviceInfo[key] = { total, used, unit: 'MB' };
          } else if (key === 'temperature') {
            // SE5/SE7/SE9 取 chip[0].temperature，否则 board[0].temperature
            if (
              deviceType === 'SE5' ||
              deviceType === 'SE7' ||
              deviceType === 'SE9'
            ) {
              this.deviceInfo[key] =
                result?.coreComputingUnit?.board?.[0]?.chip?.[0]?.temperature ?? 0;
            } else {
              this.deviceInfo[key] =
                (coreComputingUnit?.board && coreComputingUnit?.board[0]?.temperature) ||
                0;
            }
          } else if (key === 'fanSpeed') {
            this.deviceInfo[key] =
              coreComputingUnit?.board?.[0]?.fanspeedPercent ??
              (coreComputingUnit?.board && coreComputingUnit?.board[0]?.fanSpeed) ??
              0;
          } else {
            // status 暂时写死
            if (key !== 'status' && result[key] !== undefined && result[key] !== null) {
              this.deviceInfo[key] = result[key];
            }
          }
        });
        this.init();
        // 核心板数据
        const isSingleBoard = this.singleBoardArr.some((item) =>
          (deviceType || '').toLowerCase().includes(item),
        );
        if (
          !isSingleBoard &&
          coreComputingUnit?.board &&
          coreComputingUnit.board.length
        ) {
          const sortBoard = coreComputingUnit.board
            .slice()
            .sort((b1, b2) => (b1.number || 0) - (b2.number || 0));
          this.deviceStatus = sortBoard.map((board) => ({
            sn: board.boardSn,
            status: deviceRunningSatus[board.chip?.[0]?.health],
            ip: board.netCard?.[0]?.ip,
            title: `${t('overview.coreBoard')}-${board.number}`,
            number: board.number,
          }));
          sortBoard.forEach((board) => {
            const coreSys = board.coreSys || board;
            this.cpu.push({
              name: board.boardSn,
              value: (coreSys.cpu?.utilizationRate ?? board.cpu?.usage ?? 0).toFixed(1),
            });
            this.tpu.push({
              name: board.boardSn,
              value: (
                board.chip?.[0]?.utilizationRate ??
                board.chip?.[0]?.tpuUtililizationRate ??
                0
              ).toFixed(1),
            });
            const memTotal = coreSys.memory?.total ?? board.memory?.total ?? 0;
            const memAvail = coreSys.memory?.available ?? board.memory?.available ?? 0;
            const memUsage =
              memTotal > 0 ? ((memTotal - memAvail) / memTotal) * 100 : board.memory?.usage ?? 0;
            this.memory.push({ name: board.boardSn, value: memUsage.toFixed(1) });
            this.chipTemperature.push({
              name: board.boardSn,
              value: board.temperature ?? 0,
            });
            this.fanSpeed.push({
              name: board.boardSn,
              value: board.fanspeedPercent ?? board.fanSpeed ?? 0,
            });
          });
        }
        // 控制板数据
        this.cpu.push({ name: deviceSn, value: (cpuInfo?.utilizationRate ?? cpuInfo?.usage ?? 0).toFixed(1) });
        const memTotal = memory?.total ?? 0;
        const memAvail = memory?.available ?? memory?.free ?? 0;
        const memUsage = memTotal > 0 ? ((memTotal - memAvail) / memTotal) * 100 : 0;
        this.memory.push({ name: deviceSn, value: memUsage.toFixed(1) });
        if (!isSingleBoard) {
          // se6有板卡详情菜单
          const overview = asyncRoutes.find((item) => item.name === 'Overview');
          const Maintenance = asyncRoutes.find((item) => item.name === 'Maintenance');
          if (overview?.children?.[1]?.meta) overview.children[1].meta.hideMenu = false;
          if (Maintenance?.children?.[2]?.meta) Maintenance.children[2].meta.hideMenu = false;
          permissionStore.buildRoutesAction();
          permissionStore.setLastBuildMenuTime();
        }
      }
      // runTime 解析独立于 resource 是否成功：basic 成功但 resource 失败时，
      // 上面 if(result) 块被整体跳过，runTime 会停留在初始值，导致 DeviceInfo 的
      // setInterval 做 ' '+1 字符串拼接，最终生成 1.286e+122 之类的巨大数。
      // 这里以 basic.system.runtime 兜底，保证 deviceInfo.runTime 始终是数字秒数。
      const rt = (basic && basic.system && basic.system.runtime) || (result && result.runTime);
      if (rt !== undefined && rt !== null) {
        if (typeof rt === 'number' && isFinite(rt)) {
          this.deviceInfo.runTime = rt;
        } else if (typeof rt === 'string' && rt.includes(':')) {
          const s = rt.split(':');
          if (s.length >= 3) {
            this.deviceInfo.runTime =
              (parseInt(s[0], 10) || 0) * 3600 +
              (parseInt(s[1], 10) || 0) * 60 +
              (parseInt(s[2], 10) || 0);
          }
        }
      }
      return result;
    },
    updateDevice(key, value) {
      this.deviceInfo.hasOwnProperty(key) && (this.deviceInfo[key] = value);
    },
    init() {
      this.cpu = [];
      this.tpu = [];
      this.memory = [];
      this.chipTemperature = [];
      this.fanSpeed = [];
    },
  },
});
// Need to be used outside the setup
export function useUserStoreWithOut() {
  return useDeviceInfo(store);
}
