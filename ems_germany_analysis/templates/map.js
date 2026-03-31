// ── PMTiles protocol ──
const protocol = new pmtiles.Protocol();
maplibregl.addProtocol('pmtiles', protocol.tile);

// ── Map initialization ──
const map = new maplibregl.Map({
  container: 'map',
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

// ── Color scale: travel time (green → yellow → red) ──
function makeTravelColor(prop) {
  return [
    'interpolate', ['linear'],
    ['coalesce', ['get', prop], 999],
    0,   '#1a9641',
    15,  '#a6d96a',
    30,  '#ffffbf',
    45,  '#fdae61',
    60,  '#d7191c',
    999, '#aaaaaa',
  ];
}

// ── Hospital numbered icons ──
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
  const img = ctx.getImageData(0, 0, size, size);
  return { width: size, height: size, data: img.data };
}

// ── State ──
let currentProp = 'avg_travel_any';

const ZOOM_THRESHOLDS = {
  hex5km:  { min: 0,  max: 8  },
  hex1km:  { min: 8,  max: 11 },
  hex100m: { min: 11, max: 22 },
};

// ── Map load ──
map.on('load', () => {
  map.addImage('hospital-1', makeHospitalIcon('1', '#6b9ec7'));
  map.addImage('hospital-2', makeHospitalIcon('2', '#9b7dbf'));
  map.addImage('hospital-3', makeHospitalIcon('3', '#c4744d'));

  // PMTiles hex sources
  map.addSource('hexagon-5km',  { type: 'vector', url: 'pmtiles://./pmtiles/hex_5km.pmtiles'  });
  map.addSource('hexagon-1km',  { type: 'vector', url: 'pmtiles://./pmtiles/hex_1km.pmtiles'  });
  map.addSource('hexagon-100m', { type: 'vector', url: 'pmtiles://./pmtiles/hex_100m.pmtiles' });

  // Hospital GeoJSON source
  map.addSource('hospitals', { type: 'geojson', data: 'hospitals.geojson' });

  // Helper: add fill + outline layer pair for a hex resolution
  function addHexLayers(id, source, sourceLayer, minZoom, maxZoom) {
    map.addLayer({
      id: `${id}-fill`,
      type: 'fill',
      source,
      'source-layer': sourceLayer,
      minzoom: minZoom,
      maxzoom: maxZoom,
      paint: {
        'fill-color': makeTravelColor(currentProp),
        'fill-opacity': 0.75,
      },
    });
    map.addLayer({
      id: `${id}-outline`,
      type: 'line',
      source,
      'source-layer': sourceLayer,
      minzoom: minZoom,
      maxzoom: maxZoom,
      paint: { 'line-color': '#ffffff', 'line-width': 0.5, 'line-opacity': 0.4 },
    });
  }

  addHexLayers('hexagon-5km',  'hexagon-5km',  'hex_5km',  ZOOM_THRESHOLDS.hex5km.min,  ZOOM_THRESHOLDS.hex5km.max);
  addHexLayers('hexagon-1km',  'hexagon-1km',  'hex_1km',  ZOOM_THRESHOLDS.hex1km.min,  ZOOM_THRESHOLDS.hex1km.max);
  addHexLayers('hexagon-100m', 'hexagon-100m', 'hex_100m', ZOOM_THRESHOLDS.hex100m.min, ZOOM_THRESHOLDS.hex100m.max);

  // Hospital symbol layer
  map.addLayer({
    id: 'hospitals-layer',
    type: 'symbol',
    source: 'hospitals',
    layout: {
      'icon-image': [
        'match', ['to-string', ['get', 'level']],
        '1', 'hospital-1',
        '2', 'hospital-2',
        'hospital-3',
      ],
      'icon-allow-overlap': true,
      'icon-ignore-placement': true,
    },
  });

  // Labels rendered above data layers
  map.addLayer({ id: 'carto-labels-layer', type: 'raster', source: 'carto-labels' });

  // ── Side panel: show on hex hover ──
  const hexFillLayers = ['hexagon-5km-fill', 'hexagon-1km-fill', 'hexagon-100m-fill'];
  const panel = document.getElementById('hex-info-panel');
  const content = document.getElementById('hex-info-content');

  hexFillLayers.forEach(layerId => {
    map.on('mousemove', layerId, (e) => {
      map.getCanvas().style.cursor = 'pointer';
      const p = e.features[0].properties;
      const fmt = (v) => (v == null || v >= 900) ? 'n/a' : v.toFixed(1) + ' min';
      content.innerHTML = `
        <p class="panel-section-title">Travel Time</p>
        <table class="panel-table">
          <tr><td>Any hospital</td><td>${fmt(p.avg_travel_any)}</td></tr>
          <tr><td>Level 1</td><td>${fmt(p.avg_travel_l1)}</td></tr>
          <tr><td>Level 2</td><td>${fmt(p.avg_travel_l2)}</td></tr>
          <tr><td>Level 3</td><td>${fmt(p.avg_travel_l3)}</td></tr>
        </table>
        <p class="panel-section-title">Population</p>
        <table class="panel-table">
          <tr><td>Total</td><td>${(p.total_population || 0).toLocaleString()}</td></tr>
          <tr><td>Under 18</td><td>${(p.pop_under18 || 0).toLocaleString()}</td></tr>
          <tr><td>18–29</td><td>${(p.pop_18to29 || 0).toLocaleString()}</td></tr>
          <tr><td>30–49</td><td>${(p.pop_30to49 || 0).toLocaleString()}</td></tr>
          <tr><td>50–64</td><td>${(p.pop_50to64 || 0).toLocaleString()}</td></tr>
          <tr><td>65+</td><td>${(p.pop_65plus || 0).toLocaleString()}</td></tr>
        </table>
      `;
      panel.style.display = 'block';
    });

    map.on('mouseleave', layerId, () => {
      map.getCanvas().style.cursor = '';
      panel.style.display = 'none';
    });
  });

  // Hospital click popup
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

// ── Controls ──
function setLayer(level) {
  const propMap = { any: 'avg_travel_any', l1: 'avg_travel_l1', l2: 'avg_travel_l2', l3: 'avg_travel_l3' };
  currentProp = propMap[level];
  const color = makeTravelColor(currentProp);
  ['hexagon-5km-fill', 'hexagon-1km-fill', 'hexagon-100m-fill'].forEach(id => {
    map.setPaintProperty(id, 'fill-color', color);
  });
  document.querySelectorAll('.map-btn').forEach((b, i) => {
    b.classList.toggle('active', ['any', 'l1', 'l2', 'l3'][i] === level);
  });
}

function toggleHospitals(visible) {
  map.setLayoutProperty('hospitals-layer', 'visibility', visible ? 'visible' : 'none');
}
