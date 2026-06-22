import { MockMethod } from 'vite-plugin-mock';
import { resultSuccess } from '../_util';
const result = {
  pageCount: 1,
  pageNo: 1,
  pageSize: 20,
  total: 1,
  items: [
    {
      dataTime: '2022-08-05 16:39:59', //操作时间
      ID: 1,
      deviceSn: 'erer3343433', //算力设备标识
      componentType: 1, //告警类型：cpu，内存，磁盘，tpu，网卡，板卡，芯片编码待定
      contorllerUnitSn: '00:ee:11', //控制单元标识
      coreUnitBoardSn: '00:ee:11', //核心计算单元算力板/算力卡标识
      coreUnitBoardChipSn: '00:ee:11', //PCIE插卡模式，核心计算单元算力卡芯片标识
      code: -100001, //6位告警码x@yy@zzz。x:中央处理单元部分告警以-1开头；中央处理单元部分告警恢复以1开头。核心计算单元部分告警以-2开头；告警恢复以-2开头。
      msg: 'cpu使用率过高', //告警描述
    },
    {
      dataTime: '2022-08-05 16:39:59', //操作时间
      ID: 2,
      deviceSn: 'erer3343433', //算力设备标识
      componentType: 1, //告警类型：cpu，内存，磁盘，tpu，网卡，板卡，芯片编码待定
      contorllerUnitSn: '00:ee:11', //控制单元标识
      coreUnitBoardSn: '00:ee:11', //核心计算单元算力板/算力卡标识
      coreUnitBoardChipSn: '00:ee:11', //PCIE插卡模式，核心计算单元算力卡芯片标识
      code: -100001, //6位告警码x@yy@zzz。x:中央处理单元部分告警以-1开头；中央处理单元部分告警恢复以1开头。核心计算单元部分告警以-2开头；告警恢复以-2开头。
      msg: 'cpu使用率过高', //告警描述
    },
  ],
};
export default [
  {
    url: '/api/device/alarmRecord/list',
    statusCode: 200,
    method: 'get',
    response: () => {
      return resultSuccess(result);
    },
  },
] as MockMethod[];
