import { getMenuListResultModel } from './model/menuModel';

enum Api {
  GetMenuList = '/getMenuList',
}

/**
 * @description: Get user menu based on id
 * ssm 无菜单端点，菜单由前端静态路由生成，此处 mock 返回空数组。
 */
export const getMenuList = (): Promise<getMenuListResultModel> => {
  return Promise.resolve([] as getMenuListResultModel);
};
