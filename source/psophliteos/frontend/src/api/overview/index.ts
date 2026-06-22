import { defHttp } from '/@/utils/http/axios';

// import { DeviceInfoApiResponse } from '../model/baseModel';

enum Api {
  Resource = '/device/resource',
  Basic = '/device/basic',
  Operation = '/device/core/operation',
  Software = '/device/version',
}

export function resourceApi() {
  return defHttp.get({ url: Api.Resource });
}
export function resourceIp() {
  const res = defHttp.get({ url: Api.Resource }).then((res) => {
    return res.coreComputingUnit.board.map((item) => ({
      ip: item.netCard[0].ip,
    }));
  });
  return res;
}

export function setDeviceInfoApi(params) {
  return defHttp.post({ url: Api.Basic, params }, { isTransformResponse: false });
}

// 核心板启停
interface operationParams {
  devices: Array<string>;
  type: number;
}
export function operationApi(params: operationParams) {
  return defHttp.post({ url: Api.Operation, params }, { isTransformResponse: false });
}

export function getSoftwareInfoApi() {
  return defHttp.get({ url: Api.Software });
}
