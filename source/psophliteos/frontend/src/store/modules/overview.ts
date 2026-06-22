// @ts-nocheck
import { defineStore } from 'pinia';
import { store } from '/@/store';
import { resourceApi } from '/@/api/overview/index';
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
      runTime: '',
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
      const result = await resourceApi();

      if (result) {
        this.originData = result;
        const { cpu, memory, coreComputingUnit, deviceSn, deviceType } = result;
        Object.keys(this.deviceInfo).forEach((key) => {
          if (key === 'runTime') {
            const secondsArr = result[key].split(':');
            this.deviceInfo[key] = secondsArr[0] * 60 * 60 + secondsArr[1] * 60 + +secondsArr[2];
          } else if (key === 'temperature') {
            if (
              result.deviceType === 'SE5' ||
              result.deviceType === 'SE7' ||
              result.deviceType === 'SE9'
            ) {
              this.deviceInfo[key] = result?.coreComputingUnit?.board[0]?.chip[0]?.temperature;
            } else {
              this.deviceInfo[key] =
                (result.coreComputingUnit?.board && result.coreComputingUnit?.board[0][key]) || 0;
            }
          } else if (key === 'fanSpeed') {
            this.deviceInfo[key] =
              (result.coreComputingUnit?.board && result.coreComputingUnit?.board[0][key]) || 0;
          } else {
            // status 暂时写死
            if (key !== 'status') {
              this.deviceInfo[key] = result[key];
            }
          }
        });
        this.init();
        // 核心板数据
        const isSingleBoard = this.singleBoardArr.some((item) =>
          deviceType.toLowerCase().includes(item),
        );
        if (!isSingleBoard && coreComputingUnit.board && coreComputingUnit.board.length) {
          const sortBoard = coreComputingUnit.board.sort((b1, b2) => b1.number - b2.number);
          this.deviceStatus = sortBoard.map((board) => ({
            sn: board.boardSn,
            status: deviceRunningSatus[board.chip[0]?.health],
            ip: board.netCard[0]?.ip,
            // title: '核心板-' + `${board.number}`,
            title: `${t('overview.coreBoard')}-${board.number}`,
            number: board.number,
          }));
          sortBoard.forEach((board) => {
            this.cpu.push({ name: board.boardSn, value: board.cpu.usage.toFixed(1) });
            this.tpu.push({
              name: board.boardSn,
              value: board.chip[0].tpuUtililizationRate.toFixed(1),
            });
            this.memory.push({ name: board.boardSn, value: board.memory.usage.toFixed(1) });
            this.chipTemperature.push({ name: board.boardSn, value: board.temperature });
            this.fanSpeed.push({ name: board.boardSn, value: board.fanSpeed });
          });
        }
        // 控制板数据
        this.cpu.push({ name: deviceSn, value: cpu.usage.toFixed(1) });
        this.memory.push({ name: deviceSn, value: memory.usage.toFixed(1) });
        // this.chipTemperature.push({ name: deviceSn, value: 0.1 });
        // this.fanSpeed.push({ name: deviceSn, value: 0.1 });
        if (!isSingleBoard) {
          // se6有板卡详情菜单
          const overview = asyncRoutes.find((item) => item.name === 'Overview');
          const Maintenance = asyncRoutes.find((item) => item.name === 'Maintenance');
          overview.children[1].meta.hideMenu = false;
          Maintenance.children[2].meta.hideMenu = false;
          permissionStore.buildRoutesAction();
          permissionStore.setLastBuildMenuTime();
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
