import { MockMethod } from 'vite-plugin-mock';
import { resultSuccess } from '../_util';
const result = [
  {
    LastRebootTime: '0001-01-01T00:00:00Z',
    cmdFlag: '--target=all',
    createTime: '2022-08-08T12:15:31.896773107Z',
    fileName: 'core_ota.tgz',
    info: '',
    moduleName: 'core',
    name: 'se6_core_upgrade_20220808201531',
    product: 'SE6',
    status: 2,
    step: 'flash',
    strategy: 'flash',
    type: 1,
    userId: '3bdacaa2-3e67-11e9-adea-acde48001122',
    version: '',
    workflowId: 4,
  },
];
export default [
  {
    url: '/api/device/ota/upgrade',
    statusCode: 200,
    method: 'get',
    response: () => {
      return resultSuccess(result);
    },
  },
] as MockMethod[];
