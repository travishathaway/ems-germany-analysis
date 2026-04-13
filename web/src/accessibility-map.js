import maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import { Protocol } from 'pmtiles';
import { Plotly } from './plotly-loader.js';
import { dataUrl } from './data-dir.js';

const PROP_MAP  = { any: 'avg_travel_any', l1: 'avg_travel_l1', l2: 'avg_travel_l2', l3: 'avg_travel_l3' };
const LEVEL_MAP = { l1: 1, l2: 2, l3: 3 };

function makeEffectiveExpr(layers) {
  const props = [...layers].map(l => ['coalesce', ['get', PROP_MAP[l]], 999]);
  return props.length === 1 ? props[0] : ['min', ...props];
}

function makeTravelColor(layers) {
  return [
    'interpolate', ['linear'],
    makeEffectiveExpr(layers),
    0,   '#1a9641',
    15,  '#a6d96a',
    30,  '#ffffbf',
    45,  '#fdae61',
    60,  '#d7191c',
    999, '#aaaaaa',
  ];
}

function getStatsKey(layers) {
  if (layers.has('any')) return 'any';
  const sorted = [...layers].sort();
  if (sorted.length === 3) return 'any';
  return sorted.join(',');
}

function makeHospitalIcon(label, color) {
  const size = 20;
  const canvas = document.createElement('canvas');
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext('2d');
  const r = size / 2;
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.arc(r, r, r - 1, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = '#fff';
  ctx.font = `bold ${size * 0.55}px Arial, sans-serif`;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(label, r, r + 0.5);
  return { width: size, height: size, data: ctx.getImageData(0, 0, size, size).data };
}

function initMap(wrapper, stats) {
  const pmtilesDir   = dataUrl('pmtiles');
  const hospitalsSrc = dataUrl('hospitals.geojson');

  wrapper.style.position = 'relative';
  wrapper.style.overflow = 'hidden';
  wrapper.innerHTML = '<div id="map" style="position:absolute;inset:0;"></div>';

  const mapEl = wrapper.querySelector('#map');

  const infoAny = document.getElementById('info-any');
  const infoL1  = document.getElementById('info-l1');
  const infoL2  = document.getElementById('info-l2');
  const infoL3  = document.getElementById('info-l3');
  const infoPop = document.getElementById('info-pop');

  if (!maplibregl._pmtilesRegistered) {
    const protocol = new Protocol();
    maplibregl.addProtocol('pmtiles', protocol.tile);
    maplibregl._pmtilesRegistered = true;
  }

  const map = new maplibregl.Map({
    container: mapEl,
    style: {
      version: 8,
      sources: {
        'carto-base': {
          type: 'raster',
          tiles: [
            'https://a.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}.png',
            'https://b.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}.png',
            'https://c.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}.png',
          ],
          tileSize: 256,
          attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors © <a href="https://carto.com/attributions">CARTO</a>',
        },
        'carto-labels': {
          type: 'raster',
          tiles: [
            'https://a.basemaps.cartocdn.com/light_only_labels/{z}/{x}/{y}.png',
            'https://b.basemaps.cartocdn.com/light_only_labels/{z}/{x}/{y}.png',
            'https://c.basemaps.cartocdn.com/light_only_labels/{z}/{x}/{y}.png',
          ],
          tileSize: 256,
        },
      },
      layers: [{ id: 'carto-base-layer', type: 'raster', source: 'carto-base' }],
    },
    center: [10.45, 51.2],
    zoom: 5.5,
  });

  map.addControl(new maplibregl.NavigationControl(), 'top-right');

  let selectedLayers = new Set(['any']);
  let filterLevels   = null;
  let minTravelMin   = 0;

  const HOSP_COLORS = ['#6b9ec7', '#9b7dbf', '#c4744d'];
  const clusterMarkers = {};
  let clusterMarkersOnScreen = {};
  let hospitalsVisible    = true;
  let updateClusterMarkers  = () => {};
  let updateHospitalFilter  = () => {};
  let updateHexFilter       = () => {};

  function updateSummaryStats(layers) {
    if (!stats) return;
    const kpi = stats[getStatsKey(layers)];
    if (!kpi) return;
    const medianEl      = document.getElementById('stat-median');
    const cov30El       = document.getElementById('stat-cov30');
    const underservedEl = document.getElementById('stat-underserved');
    if (medianEl)      medianEl.innerHTML      = `${kpi.median} <em>min</em>`;
    if (cov30El)       cov30El.innerHTML       = `${kpi.cov30} <em>%</em>`;
    if (underservedEl) underservedEl.innerHTML = `${kpi.underserved_m} <em>M</em>`;
  }

  // Initialise summary stats for the default "any" selection
  updateSummaryStats(selectedLayers);

  map.on('load', () => {
    map.addImage('hospital-1', makeHospitalIcon('1', '#6b9ec7'));
    map.addImage('hospital-2', makeHospitalIcon('2', '#9b7dbf'));
    map.addImage('hospital-3', makeHospitalIcon('3', '#c4744d'));

    map.addSource('hexagon-5km',  { type: 'vector', url: `pmtiles://${pmtilesDir}/hex_5km.pmtiles`  });
    map.addSource('hexagon-1km',  { type: 'vector', url: `pmtiles://${pmtilesDir}/hex_1km.pmtiles`  });
    map.addSource('hexagon-100m', { type: 'vector', url: `pmtiles://${pmtilesDir}/hex_100m.pmtiles` });
    map.addSource('hospitals', {
      type: 'geojson',
      data: hospitalsSrc,
      cluster: true,
      clusterRadius: 60,
      clusterProperties: {
        'lvl1': ['+', ['case', ['==', ['get', 'level'], 1], 1, 0]],
        'lvl2': ['+', ['case', ['==', ['get', 'level'], 2], 1, 0]],
        'lvl3': ['+', ['case', ['==', ['get', 'level'], 3], 1, 0]],
      },
    });

    const addHexLayers = (id, source, sourceLayer, minZoom, maxZoom) => {
      map.addLayer({
        id: `${id}-fill`, type: 'fill', source, 'source-layer': sourceLayer,
        minzoom: minZoom, maxzoom: maxZoom,
        paint: { 'fill-color': makeTravelColor(selectedLayers), 'fill-opacity': 0.75 },
      });
      map.addLayer({
        id: `${id}-outline`, type: 'line', source, 'source-layer': sourceLayer,
        minzoom: minZoom, maxzoom: maxZoom,
        paint: { 'line-color': '#ffffff', 'line-width': 0.5, 'line-opacity': 0.4 },
      });
    };

    addHexLayers('hexagon-5km',  'hexagon-5km',  'hex_5km',  0,  8);
    addHexLayers('hexagon-1km',  'hexagon-1km',  'hex_1km',  8,  11);
    addHexLayers('hexagon-100m', 'hexagon-100m', 'hex_100m', 11, 22);

    map.addLayer({
      id: 'hospitals-layer', type: 'symbol', source: 'hospitals',
      filter: ['!=', 'cluster', true],
      layout: {
        'icon-image': ['match', ['to-string', ['get', 'level']], '1', 'hospital-1', '2', 'hospital-2', 'hospital-3'],
        'icon-allow-overlap': true,
        'icon-ignore-placement': true,
      },
    });

    map.addLayer({ id: 'carto-labels-layer', type: 'raster', source: 'carto-labels' });

    function donutSegment(start, end, r, r0, color) {
      if (end - start === 1) end -= 0.00001;
      const a0 = 2 * Math.PI * (start - 0.25);
      const a1 = 2 * Math.PI * (end - 0.25);
      const x0 = Math.cos(a0), y0 = Math.sin(a0);
      const x1 = Math.cos(a1), y1 = Math.sin(a1);
      const largeArc = end - start > 0.5 ? 1 : 0;
      return `<path d="M ${r + r0 * x0} ${r + r0 * y0} L ${r + r * x0} ${r + r * y0} A ${r} ${r} 0 ${largeArc} 1 ${r + r * x1} ${r + r * y1} L ${r + r0 * x1} ${r + r0 * y1} A ${r0} ${r0} 0 ${largeArc} 0 ${r + r0 * x0} ${r + r0 * y0}" fill="${color}" />`;
    }

    function createClusterDonut(props, filterLevels) {
      const rawCounts = [props.lvl1 || 0, props.lvl2 || 0, props.lvl3 || 0];
      const counts = filterLevels === null
        ? rawCounts
        : rawCounts.map((c, i) => (filterLevels.includes(i + 1) ? c : 0));
      const total = counts.reduce((a, b) => a + b, 0);
      if (total === 0) return null;
      const offsets = counts.reduce((acc, c) => { acc.push(acc[acc.length - 1] + c); return acc; }, [0]);
      const fontSize = total >= 1000 ? 14 : total >= 100 ? 13 : 12;
      const r  = total >= 1000 ? 28 : total >= 100 ? 22 : 16;
      const r0 = Math.round(r * 0.55);
      const w  = r * 2;
      let svg = `<svg width="${w}" height="${w}" viewBox="0 0 ${w} ${w}" text-anchor="middle" style="font:${fontSize}px sans-serif;display:block;">`;
      counts.forEach((c, i) => {
        if (c > 0) svg += donutSegment(offsets[i] / total, (offsets[i] + c) / total, r, r0, HOSP_COLORS[i]);
      });
      svg += `<circle cx="${r}" cy="${r}" r="${r0}" fill="white"/>`;
      svg += `<text dominant-baseline="central" transform="translate(${r},${r})" style="font-weight:600;">${total}</text>`;
      svg += '</svg>';
      const el = document.createElement('div');
      el.style.cursor = 'pointer';
      el.innerHTML = svg;
      el.title = filterLevels === null
        ? `${total} hospitals (L1: ${rawCounts[0]}, L2: ${rawCounts[1]}, L3: ${rawCounts[2]})`
        : `${total} hospitals (${filterLevels.map(l => `L${l}: ${rawCounts[l - 1]}`).join(', ')})`;
      return el;
    }

    updateClusterMarkers = function () {
      if (!hospitalsVisible) return;
      const newMarkers = {};
      const features = map.querySourceFeatures('hospitals');
      for (const feature of features) {
        const props = feature.properties;
        if (!props.cluster) continue;
        if (filterLevels !== null) {
          const hasAny = filterLevels.some(lvl => (props[`lvl${lvl}`] || 0) > 0);
          if (!hasAny) continue;
        }
        const id = props.cluster_id;
        let marker = clusterMarkers[id];
        if (!marker) {
          const el = createClusterDonut(props, filterLevels);
          if (!el) continue;
          marker = clusterMarkers[id] = new maplibregl.Marker({ element: el })
            .setLngLat(feature.geometry.coordinates);
        }
        newMarkers[id] = marker;
        if (!clusterMarkersOnScreen[id]) marker.addTo(map);
      }
      for (const id in clusterMarkersOnScreen) {
        if (!newMarkers[id]) clusterMarkersOnScreen[id].remove();
      }
      clusterMarkersOnScreen = newMarkers;
    };

    updateHospitalFilter = function () {
      const specificLevels = [...selectedLayers]
        .filter(l => l !== 'any')
        .map(l => LEVEL_MAP[l]);
      if (selectedLayers.has('any') || specificLevels.length === 0 || specificLevels.length === 3) {
        filterLevels = null;
        map.setFilter('hospitals-layer', ['!=', 'cluster', true]);
      } else if (specificLevels.length === 1) {
        filterLevels = specificLevels;
        map.setFilter('hospitals-layer', ['all', ['!=', 'cluster', true], ['==', 'level', specificLevels[0]]]);
      } else {
        filterLevels = specificLevels;
        map.setFilter('hospitals-layer', ['all', ['!=', 'cluster', true], ['match', ['get', 'level'], specificLevels, true, false]]);
      }
      for (const id in clusterMarkersOnScreen) clusterMarkersOnScreen[id].remove();
      clusterMarkersOnScreen = {};
      for (const id in clusterMarkers) delete clusterMarkers[id];
      updateClusterMarkers();
    };

    const hexAllLayers = [
      'hexagon-5km-fill',  'hexagon-5km-outline',
      'hexagon-1km-fill',  'hexagon-1km-outline',
      'hexagon-100m-fill', 'hexagon-100m-outline',
    ];
    updateHexFilter = function () {
      const eff = makeEffectiveExpr(selectedLayers);
      const filter = minTravelMin === 0 ? null : ['all', ['>=', eff, minTravelMin], ['<', eff, 900]];
      hexAllLayers.forEach(id => map.setFilter(id, filter));
    };

    map.on('data', (e) => {
      if (e.sourceId !== 'hospitals' || !e.isSourceLoaded) return;
      map.on('move', updateClusterMarkers);
      map.on('moveend', updateClusterMarkers);
      updateClusterMarkers();
    });

    const hexFillLayers = ['hexagon-5km-fill', 'hexagon-1km-fill', 'hexagon-100m-fill'];
    hexFillLayers.forEach(layerId => {
      map.on('mousemove', layerId, (e) => {
        map.getCanvas().style.cursor = 'pointer';
        const p = e.features[0].properties;
        const fmt = (v) => (v == null || v >= 900) ? 'n/a' : v.toFixed(1) + ' min';
        if (infoAny) infoAny.textContent = fmt(p.avg_travel_any);
        if (infoL1)  infoL1.textContent  = fmt(p.avg_travel_l1);
        if (infoL2)  infoL2.textContent  = fmt(p.avg_travel_l2);
        if (infoL3)  infoL3.textContent  = fmt(p.avg_travel_l3);
        if (infoPop) infoPop.textContent = (p.total_population || 0).toLocaleString();

        const data = [{
          type: 'pie',
          values: [p.pop_under18, p.pop_18to29, p.pop_30to49, p.pop_50to64, p.pop_65plus],
          labels: ['0-17', '18-29', '30-49', '50-64', '65+'],
          textinfo: 'label+percent',
          textposition: 'outside',
          automargin: 'top',
          marker: { colors: ['#363432', '#196774', '#90A19D', '#F0941F', '#EF6024'] },
        }];
        const layout = {
          height: 200, width: 200,
          margin: { t: 45, b: 45, l: 45, r: 45 },
          showlegend: false,
        };
        document.getElementById('demographic-pie-chart-placeholder').style.display = 'none';
        Plotly.newPlot('demographic-pie-chart-cell', data, layout, { staticPlot: true });
      });

      map.on('mouseleave', layerId, () => {
        map.getCanvas().style.cursor = '';
        if (infoAny) infoAny.textContent = '—';
        if (infoL1)  infoL1.textContent  = '—';
        if (infoL2)  infoL2.textContent  = '—';
        if (infoL3)  infoL3.textContent  = '—';
        if (infoPop) infoPop.textContent  = '—';
        document.getElementById('demographic-pie-chart-cell').innerHTML = '';
        document.getElementById('demographic-pie-chart-placeholder').style.display = 'block';
      });
    });

    map.on('click', 'hospitals-layer', (e) => {
      const p = e.features[0].properties;
      new maplibregl.Popup()
        .setLngLat(e.lngLat)
        .setHTML(`<strong>${p.name}</strong><br>Level ${p.level} hospital`)
        .addTo(map);
    });
    map.on('mouseenter', 'hospitals-layer', () => { map.getCanvas().style.cursor = 'pointer'; });
    map.on('mouseleave', 'hospitals-layer', () => { map.getCanvas().style.cursor = ''; });
  });

  const fillLayers = ['hexagon-5km-fill', 'hexagon-1km-fill', 'hexagon-100m-fill'];

  document.querySelectorAll('.map-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const layer = btn.dataset.layer;
      if (layer === 'any') {
        selectedLayers = new Set(['any']);
      } else {
        selectedLayers.delete('any');
        if (selectedLayers.has(layer)) {
          selectedLayers.delete(layer);
          if (selectedLayers.size === 0) selectedLayers.add('any');
        } else {
          selectedLayers.add(layer);
        }
      }
      document.querySelectorAll('.map-btn').forEach(b => {
        b.classList.toggle('active', selectedLayers.has(b.dataset.layer));
      });
      const color = makeTravelColor(selectedLayers);
      fillLayers.forEach(id => map.setPaintProperty(id, 'fill-color', color));
      updateHospitalFilter();
      updateHexFilter();
      updateSummaryStats(selectedLayers);
    });
  });

  document.querySelector('#travel-min-slider').addEventListener('input', (e) => {
    minTravelMin = Number(e.target.value);
    document.querySelector('#travel-min-val').textContent = minTravelMin;
    updateHexFilter();
  });

  document.querySelector('#toggle-hospitals').addEventListener('change', (e) => {
    hospitalsVisible = e.target.checked;
    map.setLayoutProperty('hospitals-layer', 'visibility', hospitalsVisible ? 'visible' : 'none');
    if (hospitalsVisible) {
      updateClusterMarkers();
    } else {
      for (const id in clusterMarkersOnScreen) clusterMarkersOnScreen[id].remove();
      clusterMarkersOnScreen = {};
    }
  });
}

document.addEventListener('DOMContentLoaded', async () => {
  const wrapper = document.getElementById('maplibre-container');
  if (!wrapper) return;

  // Fetch stats.json from data directory; gracefully degrade if unavailable
  let stats = null;
  try {
    stats = await fetch(dataUrl('stats.json')).then(r => r.json());
  } catch {
    console.warn('accessibility-map: could not load stats.json');
  }

  initMap(wrapper, stats);
});
