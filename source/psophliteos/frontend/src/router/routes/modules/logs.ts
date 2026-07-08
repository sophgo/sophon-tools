import type { AppRouteModule } from '/@/router/types';

import { LAYOUT } from '/@/router/constant';
import { t } from '/@/hooks/web/useI18n';

const logs: AppRouteModule = {
  path: '/logs',
  name: 'Logs',
  component: LAYOUT,
  redirect: '/logs/warning',
  meta: {
    orderNo: 3,
    icon: 'icon-park-outline:upload-logs',
    title: t('routes.dashboard.logs'),
    // hideMenu: true,
  },
  children: [
    {
      path: 'warning',
      name: 'Warning',
      component: () => import('/@/views/logs/warning/index.vue'),
      meta: {
        title: t('routes.dashboard.warning'),
      },
    },
    {
      path: 'operate',
      name: 'Operate',
      component: () => import('/@/views/logs/operate/index.vue'),
      meta: {
        title: t('routes.dashboard.operate'),
      },
    },
    {
      path: 'logDownload',
      name: 'logDownload',
      component: () => import('/@/views/logs/logDownload/index.vue'),
      meta: {
        title: t('routes.dashboard.logDownload'),
      },
    },
  ],
};

export default logs;
