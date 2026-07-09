import { BasicColumn } from '/@/components/Table/src/types/table';

export function getPortColumns(): BasicColumn[] {
  return [
    {
      title: '协议',
      dataIndex: 'proto',
      key: 'proto',
      width: 80,
      align: 'center',
      // 标签渲染由 index.vue 的 #bodyCell 处理（antd 3.x bodyCell 覆盖 customRender）
    },
    { title: '本地地址', dataIndex: 'local_ip', key: 'local_ip', width: 160 },
    { title: '端口', dataIndex: 'local_port', key: 'local_port', width: 90, align: 'center' },
    { title: 'PID', dataIndex: 'pid', key: 'pid', width: 80, align: 'center' },
    { title: '进程', dataIndex: 'process', key: 'process', width: 160 },
    { title: '命令行', dataIndex: 'cmdline', key: 'cmdline', ellipsis: true },
  ];
}
