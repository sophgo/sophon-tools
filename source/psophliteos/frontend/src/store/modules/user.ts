import type { UserInfo } from '/#/store';
import type { ErrorMessageMode } from '/#/axios';
import { defineStore } from 'pinia';
import { store } from '/@/store';
import { RoleEnum } from '/@/enums/roleEnum';
import { PageEnum } from '/@/enums/pageEnum';
import { ROLES_KEY, TOKEN_KEY, USER_INFO_KEY, FIRST_LOGIN_KEY } from '/@/enums/cacheEnum';
import { getAuthCache, setAuthCache } from '/@/utils/auth';
import { GetUserInfoModel, LoginParams } from '/@/api/sys/model/userModel';
import { doLogout, loginApi } from '/@/api/sys/user';
import { getSsoActive, ssoRegister } from '/@/api/sso';
import { useI18n } from '/@/hooks/web/useI18n';
import { useMessage } from '/@/hooks/web/useMessage';
import { router } from '/@/router';
import { usePermissionStore } from '/@/store/modules/permission';
import { RouteRecordRaw } from 'vue-router';
import { PAGE_NOT_FOUND_ROUTE } from '/@/router/routes/basic';
import { isArray } from '/@/utils/is';
import { h } from 'vue';
import { Modal } from 'ant-design-vue';
import { LoginStateEnum, useLoginState } from '/@/views/sys/login/useLogin';
const { setLoginState } = useLoginState();

// SSO 推送长连接（被新登录踢下线时服务端主动推送，无需刷新）。
let ssoES: EventSource | null = null;

interface UserState {
  userInfo: Nullable<UserInfo>;
  token?: string;
  roleList: RoleEnum[];
  sessionTimeout?: boolean;
  lastUpdateTime: number;
  isFirstLogin: boolean;
}

export const useUserStore = defineStore({
  id: 'app-user',
  state: (): UserState => ({
    // user info
    userInfo: null,
    // token
    token: undefined,
    // roleList
    roleList: [],
    // Whether the login expired
    sessionTimeout: false,
    // Last fetch time
    lastUpdateTime: 0,
    // first login
    isFirstLogin: true,
  }),
  getters: {
    getUserInfo(): UserInfo {
      return this.userInfo || getAuthCache<UserInfo>(USER_INFO_KEY) || {};
    },
    getToken(): string {
      return this.token || getAuthCache<string>(TOKEN_KEY);
    },
    getIsFirstLogin(): boolean {
      return this.isFirstLogin || getAuthCache<boolean>(FIRST_LOGIN_KEY);
    },
    getRoleList(): RoleEnum[] {
      return this.roleList.length > 0 ? this.roleList : getAuthCache<RoleEnum[]>(ROLES_KEY);
    },
    getSessionTimeout(): boolean {
      return !!this.sessionTimeout;
    },
    getLastUpdateTime(): number {
      return this.lastUpdateTime;
    },
  },
  actions: {
    setToken(info: string | undefined) {
      this.token = info ? info : ''; // for null or undefined value
      setAuthCache(TOKEN_KEY, info);
    },
    setFirstLogin(firstLogin: boolean) {
      this.isFirstLogin = firstLogin;
      setAuthCache(FIRST_LOGIN_KEY, firstLogin);
    },
    setRoleList(roleList: RoleEnum[]) {
      this.roleList = roleList;
      setAuthCache(ROLES_KEY, roleList);
    },
    setUserInfo(info: UserInfo | null) {
      this.userInfo = info;
      this.lastUpdateTime = new Date().getTime();
      setAuthCache(USER_INFO_KEY, info);
    },
    setSessionTimeout(flag: boolean) {
      this.sessionTimeout = flag;
    },
    resetState() {
      this.userInfo = null;
      this.token = '';
      this.roleList = [];
      this.sessionTimeout = false;
      this.isFirstLogin = true;
    },
    /**
     * @description: login
     */
    async login(
      params: LoginParams & {
        goHome?: boolean;
        mode?: ErrorMessageMode;
      },
    ): Promise<GetUserInfoModel | null> {
      try {
        const { goHome = true, mode = 'none' as ErrorMessageMode, ...loginParams } = params;

        // 单点登录预检：若已有"另一用户"在线，弹窗确认是否继续（继续将踢掉前者）。
        // 同用户重复登录不提示（视为刷新）。
        const sso = await getSsoActive().catch(() => null);
        if (sso?.active && sso.username && sso.username !== loginParams.username) {
          const ok = await confirmKickUser(sso.username);
          if (!ok) return null;
        }

        const data = await loginApi(loginParams, mode);

        const { token, changePass, role } = data as any;
        // save token
        this.setToken(token);
        // 注册为活跃会话（踢掉之前的会话）。必须 await：register 要先于跳转后 overview
        // 发出的 /api/v1/* 鉴权请求到达服务端，否则此时活跃会话仍是旧用户，你的请求会被
        // SSO 中间件判为 401 SESSION_OFFLINE → 被弹回登录页（"登录后 overview 刷新跳登录"）。
        await ssoRegister(loginParams.username, token).catch(() => {});
        // ssm 返回 changePass 为 boolean 或 1，均视为需改密
        const needChange = changePass === true || changePass === 1;
        this.setFirstLogin(needChange);
        // 保存 role（ssm 无 getUserInfo 端点，role 从 login result 取）
        if (role) {
          this.setRoleList([role] as unknown as RoleEnum[]);
        }

        if (needChange) {
          setLoginState(LoginStateEnum.CHANGE_PASSWORD);
          return null;
        }

        // 建立 SSE 长连接，监听"被新登录踢下线"的主动推送（无需刷新即可收到提示）
        this.openSsoStream(token, loginParams.username);
        return this.afterLoginAction(goHome);
      } catch (error) {
        return Promise.reject(error);
      }
    },
    async afterLoginAction(goHome?: boolean): Promise<GetUserInfoModel | null> {
      if (!this.getToken) return null;
      // get user info
      const userInfo = await this.getUserInfoAction();
      const sessionTimeout = this.sessionTimeout;
      if (sessionTimeout) {
        this.setSessionTimeout(false);
      } else {
        const permissionStore = usePermissionStore();
        if (!permissionStore.isDynamicAddedRoute) {
          const routes = await permissionStore.buildRoutesAction();
          routes.forEach((route) => {
            router.addRoute(route as unknown as RouteRecordRaw);
          });
          router.addRoute(PAGE_NOT_FOUND_ROUTE as unknown as RouteRecordRaw);
          permissionStore.setDynamicAddedRoute(true);
        }
        goHome && (await router.replace(userInfo?.homePath || PageEnum.BASE_HOME));
      }
      return userInfo;
    },
    async getUserInfoAction(): Promise<UserInfo | null> {
      if (!this.getToken) return null;
      // const userInfo = await getUserInfo();
      const userInfo = {
        userId: '1',
        username: 'admin',
        realName: '管理员',
        avatar: '',
        desc: 'manager',
        password: 'admin',
        token: 'fakeToken1',
        homePath: '',
        roles: [
          {
            roleName: 'Super Admin',
            value: 'super',
          },
        ],
      };
      const { roles = [] } = userInfo;
      if (isArray(roles)) {
        const roleList = roles.map((item) => item.value) as RoleEnum[];
        this.setRoleList(roleList);
      } else {
        userInfo.roles = [];
        this.setRoleList([]);
      }
      this.setUserInfo(userInfo);
      return userInfo;
    },
    /**
     * @description: logout
     */
    async logout(goLogin = false) {
      // 关闭 SSO 推送长连接（避免登出后仍持有旧连接）
      this.closeSsoStream();
      if (this.getToken) {
        try {
          await doLogout({
            token: this.getToken,
          });
        } catch {
          console.log('注销Token失败');
        }
        // 同步清除 sophliteos 单点登录活跃会话（仅本 token 匹配时清）
        const { ssoLogout } = await import('/@/api/sso');
        ssoLogout().catch(() => {});
      }
      this.setToken(undefined);
      this.setSessionTimeout(false);
      this.setUserInfo(null);
      goLogin && router.push(PageEnum.BASE_LOGIN);
    },

    /**
     * @description: Confirm before logging out
     */
    confirmLoginOut() {
      const { createConfirm } = useMessage();
      const { t } = useI18n();
      createConfirm({
        iconType: 'warning',
        title: () => h('span', t('sys.app.logoutTip')),
        content: () => h('span', t('sys.app.logoutMessage')),
        onOk: async () => {
          await this.logout(true);
        },
      });
    },

    // 建立 SSO 推送长连接：登录后监听"被新登录踢下线"事件，收到即弹窗并登出。
    openSsoStream(token: string, username: string) {
      this.closeSsoStream();
      const base = (import.meta.env.VITE_GLOB_API_URL || '/api').replace(/\/$/, '');
      const url = `${base}/sso/events?token=${encodeURIComponent(token)}`;
      const es = new EventSource(url);
      ssoES = es;
      es.addEventListener('SESSION_OFFLINE', () => {
        // 被踢：关连接 → 清本地登录态 → 弹窗提示 → 跳登录页
        this.closeSsoStream();
        this.setToken(undefined);
        this.setUserInfo(null);
        Modal.info({
          title: '账号已在别处登录',
          content: h(
            'p',
            { style: { lineHeight: '1.8' } },
            `您的账号「${username}」已在另一处登录，本会话已下线。`,
          ),
          okText: '重新登录',
          onOk: () => {
            router.push(PageEnum.BASE_LOGIN);
          },
        });
      });
    },
    // 关闭 SSO 推送长连接。
    closeSsoStream() {
      if (ssoES) {
        ssoES.close();
        ssoES = null;
      }
    },
  },
});

// Need to be used outside the setup
export function useUserStoreWithOut() {
  return useUserStore(store);
}

// confirmKickUser 单点登录冲突确认：已有另一用户 online，是否继续登录（踢掉前者）。
// 返回 true=继续，false=取消。
export function confirmKickUser(activeUsername: string): Promise<boolean> {
  return new Promise((resolve) => {
    Modal.confirm({
      title: '已有用户在线',
      content: h(
        'div',
        { style: { lineHeight: '1.8' } },
        [
          h('p', {}, `当前已有用户「${activeUsername}」在线。`),
          h('p', { style: { color: '#fa8c16' } }, '继续登录将导致该用户下线。'),
          h('p', {}, '是否继续登录？'),
        ],
      ),
      okText: '继续登录',
      cancelText: '取消',
      onOk: () => resolve(true),
      onCancel: () => resolve(false),
    });
  });
}
