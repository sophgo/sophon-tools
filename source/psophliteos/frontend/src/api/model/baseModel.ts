export interface BasicPageParams {
  page: number;
  pageSize: number;
}

export interface BasicFetchResult<T> {
  items: T[];
  total: number;
}

export interface BasicApiResponse {
  code: number;
  msg: string;
  result?: Array<object>;
}
export interface VideoApiResponse {
  code: number;
  msg: string;
  result: object;
  device: Array<object>;
}
export interface DeviceInfo {
  cpu: object;
}

export interface DeviceInfoApiResponse {
  code: number;
  msg: string;
  result?: DeviceInfo;
}
