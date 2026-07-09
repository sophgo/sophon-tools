/**
 *  Introduces component library styles on demand.
 * https://github.com/anncwb/vite-plugin-style-import
 */

import { createStyleImportPlugin } from 'vite-plugin-style-import';

export function configStyleImportPlugin() {
  const pwaPlugin = createStyleImportPlugin({
    libs: [
      {
        libraryName: 'ant-design-vue',
        esModule: true,
        resolveStyle: (name) => {
          // antd 3.x 子组件共用父组件 style（无独立 style 目录）
          let styleName = name;
  const map: Record<string, string> = {
            'input-password': 'input',
            'input-search': 'input',
            'input-group': 'input',
            'textarea': 'input',
            'checkbox-group': 'checkbox',
            'radio-group': 'radio',
            'radio-button': 'radio',
            'button-group': 'button',
            'range-picker': 'date-picker',
            'month-picker': 'date-picker',
            'week-picker': 'date-picker',
          };
          styleName = map[name] || name;
          return `ant-design-vue/es/${styleName}/style/index`;
        },
      },
    ],
  });
  return pwaPlugin;
}
