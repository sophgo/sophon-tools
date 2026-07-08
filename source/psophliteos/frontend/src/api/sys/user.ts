import { defHttp } from '/@/utils/http/axios';
import {
  LoginParams,
  LogoutParams,
  LoginResultModel,
  GetUserInfoModel,
  PasswordParams,
} from './model/userModel';

import { ErrorMessageMode } from '/#/axios';

enum Api {
  Login = '/v1/login',
  Logout = '/v1/logout',
  GetUserInfo = '/v1/user',
  GetPermCode = '/v1/getPermCode',
  Password = '/v1/password',
  TestRetry = '/testRetry',
}

/**
 * @description: user login api
 */
export function loginApi(params: LoginParams, mode: ErrorMessageMode = 'message') {
  return defHttp.post<LoginResultModel>(
    {
      url: Api.Login,
      params,
    },
    {
      errorMessageMode: mode,
      noSuccessMessage: true,
    },
  );
}

/**
 * @description: getUserInfo（ssm 无 getUserInfo 端点，前端 mock）
 */
export function getUserInfo() {
  return Promise.resolve({
    userId: '1',
    username: 'admin',
    realName: '管理员',
    avatar: '',
    desc: 'manager',
    homePath: '',
    roles: [{ roleName: 'Super Admin', value: 'super' }],
  } as GetUserInfoModel);
}

export function getPermCode() {
  // ssm 无权限码端点，mock
  return Promise.resolve([] as string[]);
}

export function doLogout(params: LogoutParams) {
  return defHttp.post<LoginResultModel>({ url: Api.Logout, params }, { noSuccessMessage: true });
}

export function testRetry() {
  return defHttp.get(
    { url: Api.TestRetry },
    {
      retryRequest: {
        isOpenRetry: true,
        count: 5,
        waitTime: 1000,
      },
    },
  );
}

// 修改密码
export function changePassword(params: PasswordParams) {
  return defHttp.post({ url: Api.Password, params });
}
