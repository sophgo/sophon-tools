import type { AppRouteModule } from '/@/router/types';

import { LAYOUT } from '/@/router/constant';
import { t } from '/@/hooks/web/useI18n';

const overview: AppRouteModule = {
  path: '/overview',
  name: 'Overview',
  component: LAYOUT,
  redirect: '/overview/index',
  meta: {
    orderNo: 1,
    icon: 'bx:grid-alt',
    title: t('routes.dashboard.basicInfor'),
    // hideChildrenInMenu: true,
    // hideMenu: true,
  },
  children: [
    {
      path: 'index',
      name: 'OverviewPage',
      component: () => import('/@/views/overview/index.vue'),
      meta: {
        title: t('routes.dashboard.ovewview'),
        // icon: 'simple-icons:about-dot-me',
        // hideBreadcrumb: true, // 在隐藏面包屑中，隐藏当前菜单
      },
    },
    {
      path: 'detail',
      name: 'OverviewDetail',
      component: () => import('/@/views/overview/detail.vue'),
      meta: {
        title: t('routes.dashboard.boardDetail'),
        hideMenu: true,
        // icon: 'simple-icons:about-dot-me',
        // hideBreadcrumb: true, // 在隐藏面包屑中，隐藏当前菜单
      },
    },
    {
      path: 'detail/:sn',
      name: 'OverviewDetailDny',
      component: () => import('/@/views/overview/detail.vue'),
      meta: {
        currentActiveMenu: '/overview/detail',
        hideMenu: true,
        title: t('routes.dashboard.boardDetail'),
        // icon: 'simple-icons:about-dot-me',
        // hideBreadcrumb: true, // 在隐藏面包屑中，隐藏当前菜单
        realPath: '/overview/detail',
        dynamicLevel: 1,
      },
    },
  ],
};

export default overview;
