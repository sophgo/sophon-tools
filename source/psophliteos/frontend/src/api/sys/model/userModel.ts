/**
 * @description: Login interface parameters
 */
export interface LoginParams {
  username: string;
  password: string;
}

export interface LogoutParams {
  token: string;
}

export interface RoleInfo {
  roleName: string;
  value: string;
}

/**
 * @description: Login interface return value（对齐 ssm /api/v1/login）
 */
export interface LoginResultModel {
  token: string;
  expiresAt?: string | number;
  role?: RoleInfo | string;
  changePass?: boolean | number;
}

/**
 * @description: Get user information return value
 */
export interface GetUserInfoModel {
  roles: RoleInfo[];
  // 用户id
  userId: string | number;
  // 用户名
  username: string;
  // 真实名字
  realName: string;
  // 头像
  avatar: string;
  // 介绍
  desc?: string;
}

export interface PasswordParams {
  oldPassword: string;
  newPassword: string;
}
