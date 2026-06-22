import { defHttp } from '/@/utils/http/axios';

import { AlarmRecordParams } from './model/index';
import { BasicApiResponse } from '../model/baseModel';

enum Api {
  AlarmRecord = '/device/alarmRecord/list',
  OperRecord = '/device/operRecord/list',
  logDownload = '/down/log',
}

export function getAlarmRecord(params: AlarmRecordParams) {
  return defHttp.get<BasicApiResponse>({ url: Api.AlarmRecord, params });
}

export function getOperRecord(params: AlarmRecordParams) {
  return defHttp.get<BasicApiResponse>({ url: Api.OperRecord, params });
}

export function LogDownload() {
  return defHttp.get(
    {
      url: Api.logDownload,
      headers: {
        'Content-Type': 'application/json; application/octet-steam;application/x-compressed-tar',
      },
      responseType: 'blob',
    },
    {
      isReturnNativeResponse: true,
    },
  );
}
