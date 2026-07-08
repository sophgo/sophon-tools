/**
 * Vite plugin for SVG icons (sprite) — virtual:svg-icons-register
 * https://github.com/anncwb/vite-plugin-svg-icons
 */
import { createSvgIconsPlugin } from 'vite-plugin-svg-icons';
import { resolve } from 'path';

export function configSvgIconsPlugin() {
  return createSvgIconsPlugin({
    iconDirs: [resolve(process.cwd(), 'src/assets/icons')],
    symbolId: 'icon-[dir]-[name]',
  });
}
