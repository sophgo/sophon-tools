import { defHttp } from '/@/utils/http/axios';

// 端点对齐 ssm /api/v1/*（经 sophliteos 反代）

enum Api {
  Resource = '/v1/device/resource',
  Basic = '/v1/device/basic',
  SetBasic = '/v1/device/configure/basic',
  Operation = '/v1/hardware/exec',
  Software = '/device/version', // 本地 sophliteos 端点（保留）
}

export function resourceApi() {
  return defHttp.get({ url: Api.Resource });
}

// ssm GetCtrlBasic：返回 { chipSn, configure{basic{deviceName,deviceType}}, ipList[], system{operatingSystem,runtime,bmssmVersion,buildTime,sdkVersion,...} }
// deviceName/sdkVersion/operatingSystem/runTime 不在 resource 里，需调 basic 补齐。
export function basicApi() {
  return defHttp.get({ url: Api.Basic });
}
export function resourceIp() {
  const res = defHttp
    .get({ url: Api.Resource })
    .then((res) => {
      const board = res?.coreComputingUnit?.board || [];
      return board.map((item) => ({
        ip: item?.netCard?.[0]?.ip || '',
      }));
    })
    .catch(() => [] as any);
  return res;
}

export function setDeviceInfoApi(params) {
  return defHttp.post({ url: Api.SetBasic, params }, { isTransformResponse: false });
}

// 核心板启停（ssm 无对应端点，前端 mock）
interface operationParams {
  devices: Array<string>;
  type: number;
}
export function operationApi(_params: operationParams) {
  return Promise.resolve({ code: 0, msg: 'ok' });
}

export function getSoftwareInfoApi() {
  return defHttp.get({ url: Api.Software });
}

