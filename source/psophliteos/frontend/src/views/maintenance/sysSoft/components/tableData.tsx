import { BasicColumn } from '/@/components/Table/src/types/table';
import { useI18n } from '/@/hooks/web/useI18n';
import { useDeviceInfo } from '/@/store/modules/overview';
const deviceStore = useDeviceInfo();
const { t } = useI18n();

export function getBasicColumns(): BasicColumn[] {
  const arr = [
    {
      title: t('maintenance.systemUpdate.taskList.name'),
      dataIndex: 'name',
      align: 'center',
      ellipsis: true,
    },
    {
      title: t('maintenance.systemUpdate.taskList.product'),
      dataIndex: 'product',
      align: 'left',
      width: 160,
    },
    {
      title: t('maintenance.systemUpdate.taskList.moduleName'),
      dataIndex: 'moduleName',
      align: 'left',
      width: 160,
    },
    {
      title: t('maintenance.systemUpdate.taskList.status'),
      dataIndex: 'status',
      align: 'left',
      width: 160,
    },
    {
      title: t('maintenance.systemUpdate.taskList.step'),
      dataIndex: 'step',
      align: 'left',
      width: 160,
    },
    {
      title: t('maintenance.systemUpdate.taskList.strategy'),
      dataIndex: 'strategy',
      align: 'left',
      width: 160,
    },
    {
      title: t('maintenance.systemUpdate.taskList.type'),
      dataIndex: 'type',
      align: 'left',
      width: 160,
    },
    {
      title: t('maintenance.systemUpdate.taskList.fileName'),
      dataIndex: 'fileName',
      align: 'left',
    },
    {
      title: t('maintenance.systemUpdate.taskList.createTime'),
      dataIndex: 'createTime',
      align: 'left',
      ellipsis: true,
    },
  ];
  if (deviceStore.isSingleBoard) {
    arr.splice(1, 2);
  }
  return arr;
}
