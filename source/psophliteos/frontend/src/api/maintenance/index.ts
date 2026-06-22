import { defHttp } from '/@/utils/http/axios';
import { useGlobSetting } from '/@/hooks/setting';

import {
  IpSetParams,
  AlarmParams,
  RollbackParams,
  // UploadFileParamsSys,
  UploadApiResult,
} from './model/index';
import { BasicApiResponse } from '../model/baseModel';

const { uploadUrl = '' } = useGlobSetting();

enum Api {
  IpSet = '/device/ip',
  Alarm = '/device/configure/alarm',
  Upgrade = '/device/ota/upgrade',
  // Upload = '/api/device/ota/upgrade',
  Rollback = '/device/ota/rollback',
  SsmList = '/ssm/list',
  SysTables = '/device/iptable/get',
  deleteUserIp = '/device/iptable/delete',
  addUserIp = '/device/iptable/add',
  getComIP = '/device/basic',
  modComIP = '/device/mod',
}

// IP地址设置
export function ipSet(params: IpSetParams) {
  return defHttp.post<BasicApiResponse>({ url: Api.IpSet, params }, { isTransformResponse: false });
}

// IP地址查询
export function ipGet() {
  return defHttp.get({ url: Api.IpSet });
}

// 告警阈值设置
export function setAlarm(params: AlarmParams) {
  return defHttp.post<BasicApiResponse>({ url: Api.Alarm, params });
}

// 告警阈值查询
export function getAlarm() {
  return defHttp.get({ url: Api.Alarm });
}

// OTA一键升级
export function upgradeApi(params, onUploadProgress: (progressEvent: ProgressEvent) => void) {
  return defHttp.uploadFile<UploadApiResult>(
    {
      url: uploadUrl,
      onUploadProgress,
      // timeout: 1000 * 60 * 60 * 24,   超时时间改成15分钟
      timeout: 1000 * 60 * 15,
      // @ts-ignore
      requestOptions: {
        ignoreCancelToken: false,
        isReturnNativeResponse: true,
      },
    },
    params,
  );
}
export function checkFileList() {
  return defHttp.get({
    url: '/device/ota/list',
  });
}

//上传文件
export function checkFile(params, onUploadProgress: (progressEvent: ProgressEvent) => void) {
  return defHttp.uploadFile<UploadApiResult>(
    {
      url: '/api/device/ota/file',
      onUploadProgress,
      timeout: 1000 * 60 * 60 * 24,
      // timeout: 1000 * 60 * 15,超时时间改成15分钟
      // @ts-ignore
      requestOptions: {
        ignoreCancelToken: false,
        isTransformResponse: false,
      },
    },
    params,
  );
}
//分片上传文件
export function uploadPartFile(params, onUploadProgress: (progressEvent: ProgressEvent) => void) {
  return defHttp.uploadFile<UploadApiResult>(
    {
      url: '/api/device/ota/chunked',
      onUploadProgress,
      timeout: 1000 * 60 * 5,
      // @ts-ignore
      requestOptions: {
        ignoreCancelToken: false,
        isTransformResponse: false,
        errorMessageMode: 'none',
        retryRequest: {
          isOpenRetry: true,
          count: 2,
          waitTime: 100,
        },
      },
    },
    params,
  );
}

// 软件升级
export function upgradeSoftApi(params, onUploadProgress: (progressEvent: ProgressEvent) => void) {
  return defHttp.uploadFile<UploadApiResult>(
    {
      url: '/api/upgrade',
      onUploadProgress,
      timeout: 1000 * 60 * 15,
      // @ts-ignore
      requestOptions: {
        ignoreCancelToken: false,
        isReturnNativeResponse: true,
      },
    },
    params,
  );
}

// ssm升级
export function upgradeSsmApi(params, onUploadProgress: (progressEvent: ProgressEvent) => void) {
  return defHttp.uploadFile<UploadApiResult>(
    {
      url: '/api/ssm/upgrade',
      onUploadProgress,
      timeout: 1000 * 60 * 15,
      // @ts-ignore
      requestOptions: {
        ignoreCancelToken: false,
        isReturnNativeResponse: true,
      },
    },
    params,
  );
}

// OTA升级状态
export function upgradeStatusApi() {
  return defHttp.get({ url: Api.Upgrade });
}

// OTA一键回滚
export function rollbackApi(params: RollbackParams) {
  return defHttp.post({ url: Api.Rollback, params });
}

// OTA升级状态
export function ssmStatusApi() {
  return defHttp.get({ url: Api.SsmList });
}

export function getSysTables() {
  const res = defHttp.get({ url: Api.SysTables }).then((res) => {
    return res.sysTables;
  });

  return res;
}
export function getUserTables() {
  const res = defHttp.get({ url: Api.SysTables }).then((res) => {
    return res.userTables;
  });

  return res;
}

export function DeleteUserTables(params: any) {
  return defHttp.post({ url: Api.deleteUserIp, params });
}

export function addUserMap(params: any) {
  return defHttp.post({ url: Api.addUserIp, params });
}

export function getComIP() {
  return defHttp.get({ url: Api.getComIP }).then((res) => {
    return res.configure;
  });
}

export function modComIP(params: any) {
  return defHttp.post({ url: Api.modComIP, params });
}
