export interface IpSetParams {
  device: string;
  ipType: number; // ip类型 1静态ip 2动态ip
  ip: string; // ip地址
  subnetMask: string; // 子网掩码
  gateway: string; // 网关
  dns: string; // dns
}

export interface AlarmParams {
  fanSpeed: number; // 风扇转速
  boardTemperature: number; // 主板温度
  coreTemperature: number; // 芯片结温
  cpuRate: number; // cpu使用率
  totalMemoryScale: number; // 内存使用率
  // systemScale: number; // system内存使用率
  // videoScale: number; // video内存使用率
  tpuScale: number; // tpu内存使用率
  // externalHardDiskRate: number; // 外挂存储使用率
  diskRate: number; // 存储使用率
  tpuRate: number;
}

export interface RollbackParams {
  workflowId: number;
}

// multipart/form-data: upload file
export interface UploadFileParamsSys {
  // Other parameters
  module: string;
  // file name
  file: File | Blob;
  // file name
  ip?: string;
}
export interface UploadApiResult {
  msg: string;
  code: number;
  result: string;
}

export interface BasicPageParams {
  pageNo: number;
  pageSize: number;
}
