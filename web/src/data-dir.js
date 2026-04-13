/**
 * data-dir.js
 *
 * Single source of truth for the data directory baked in at build time.
 * All components and the map use this to construct data file URLs.
 *
 * Default: '.' — data files sit next to index.html.
 * Override at build time: VITE_DATA_DIR=./my-data npm run build
 */

const DATA_DIR = __DATA_DIR__;

/**
 * Returns a URL to a data file, rooted at the configured DATA_DIR.
 * Strips any accidental double-slashes.
 *
 * @param {string} filename  e.g. 'chart-cdf.json' or 'pmtiles/hex_5km.pmtiles'
 * @returns {string}
 */
export function dataUrl(filename) {
  return `${DATA_DIR}/${filename}`.replace(/([^:])\/\//g, '$1/');
}
