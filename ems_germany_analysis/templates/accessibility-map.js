(function () {
  const PMTILES_JS  = 'https://unpkg.com/pmtiles@3.2.0/dist/pmtiles.js';
  const MAPLIBRE_JS = 'https://unpkg.com/maplibre-gl@4/dist/maplibre-gl.js';
  const MAPLIBRE_CSS = 'https://unpkg.com/maplibre-gl@4/dist/maplibre-gl.css';

  const TEMPLATE = document.createElement('template');
  TEMPLATE.innerHTML = `
    <style>
      *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
      :host { display: block; position: relative; overflow: hidden; }
      #map { width: 100%; height: 100%; }

      #map-controls {
        position: absolute;
        top: 12px;
        left: 12px;
        background: rgba(255,255,255,0.95);
        padding: 12px 16px;
        border-radius: 8px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.2);
        z-index: 10;
        font-size: 0.85rem;
        font-family: "Helvetica Neue", Arial, sans-serif;
      }
      #map-controls strong { display: block; margin-bottom: 8px; color: #1a3a5c; }
      .map-btn {
        display: block;
        width: 100%;
        margin-bottom: 5px;
        padding: 5px 10px;
        border: 1px solid #ccc;
        border-radius: 4px;
        background: #f5f5f5;
        cursor: pointer;
        font-size: 0.82rem;
        text-align: left;
        transition: background 0.15s;
      }
      .map-btn.active { background: #1a3a5c; color: #fff; border-color: #1a3a5c; }
      .map-btn:hover:not(.active) { background: #e8eef5; }
      hr { margin: 8px 0; border: none; border-top: 1px solid #ddd; }
      label.hospital-toggle { display: flex; align-items: center; gap: 6px; cursor: pointer; font-size: 0.82rem; }

      #map-legend {
        position: absolute;
        bottom: 30px;
        right: 12px;
        background: rgba(255,255,255,0.95);
        padding: 10px 14px;
        border-radius: 8px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.2);
        z-index: 10;
        font-size: 0.82rem;
        font-family: "Helvetica Neue", Arial, sans-serif;
      }
      #map-legend strong { display: block; margin-bottom: 6px; color: #1a3a5c; }
      .legend-row { display: flex; align-items: center; gap: 8px; margin: 3px 0; }
      .legend-dot { width: 12px; height: 12px; border-radius: 50%; flex-shrink: 0; }
      .legend-grad {
        width: 130px; height: 12px; border-radius: 3px;
        background: linear-gradient(to right, #1a9641, #a6d96a, #ffffbf, #fdae61, #d7191c);
      }
      .legend-labels { display: flex; justify-content: space-between; font-size: 0.78rem; color: #666; }

      #hex-info-panel {
        position: absolute;
        right: 0; top: 0; bottom: 0;
        width: 260px;
        background: rgba(255,255,255,0.97);
        padding: 16px;
        overflow-y: auto;
        box-shadow: -2px 0 8px rgba(0,0,0,0.15);
        z-index: 10;
        font-size: 0.83rem;
        font-family: "Helvetica Neue", Arial, sans-serif;
        pointer-events: none;
        display: none;
      }
      #hex-info-panel h4 {
        color: #1a3a5c;
        font-size: 0.95rem;
        margin-bottom: 12px;
        padding-bottom: 8px;
        border-bottom: 1px solid #eee;
      }
      .panel-section-title {
        font-weight: 600;
        color: #1a3a5c;
        margin: 10px 0 4px;
        font-size: 0.82rem;
        text-transform: uppercase;
        letter-spacing: 0.05em;
      }
      .panel-table { width: 100%; border-collapse: collapse; font-size: 0.82rem; }
      .panel-table td { padding: 3px 0; }
      .panel-table td:last-child { text-align: right; font-weight: 500; }
    </style>

    <div id="map"></div>

    <div id="map-controls">
      <strong>Show travel time to:</strong>
      <button class="map-btn active" data-layer="any">Any hospital</button>
      <button class="map-btn" data-layer="l1">Level 1 hospitals</button>
      <button class="map-btn" data-layer="l2">Level 2 hospitals</button>
      <button class="map-btn" data-layer="l3">Level 3 hospitals</button>
      <hr>
      <label class="hospital-toggle">
        <input type="checkbox" id="toggle-hospitals" checked>
        Show hospitals
      </label>
    </div>

    <div id="map-legend">
      <strong>Travel time (min)</strong>
      <div class="legend-row"><div class="legend-grad"></div></div>
      <div class="legend-labels"><span>0</span><span>15</span><span>30</span><span>45</span><span>60+</span></div>
      <br>
      <strong>Hospitals</strong>
      <div class="legend-row">
        <svg width="20" height="20" viewBox="0 0 20 20"><circle cx="10" cy="10" r="9" fill="#6b9ec7"/><text x="10" y="14" text-anchor="middle" font-family="Arial,sans-serif" font-size="11" font-weight="bold" fill="#fff">1</text></svg>
        Level 1
      </div>
      <div class="legend-row">
        <svg width="20" height="20" viewBox="0 0 20 20"><circle cx="10" cy="10" r="9" fill="#9b7dbf"/><text x="10" y="14" text-anchor="middle" font-family="Arial,sans-serif" font-size="11" font-weight="bold" fill="#fff">2</text></svg>
        Level 2
      </div>
      <div class="legend-row">
        <svg width="20" height="20" viewBox="0 0 20 20"><circle cx="10" cy="10" r="9" fill="#c4744d"/><text x="10" y="14" text-anchor="middle" font-family="Arial,sans-serif" font-size="11" font-weight="bold" fill="#fff">3</text></svg>
        Level 3
      </div>
    </div>

    <div id="hex-info-panel">
      <h4>Hexagon Details</h4>
      <div id="hex-info-content"></div>
    </div>
  `;

  function loadScript(src) {
    return new Promise(resolve => {
      if (document.querySelector(`script[src="${src}"]`)) { resolve(); return; }
      const s = document.createElement('script');
      s.src = src;
      s.onload = resolve;
      document.head.appendChild(s);
    });
  }

  class AccessibilityMap extends HTMLElement {
    connectedCallback() {
      this._shadow = this.attachShadow({ mode: 'open' });
      this._shadow.appendChild(TEMPLATE.content.cloneNode(true));

      // Inject MapLibre CSS into shadow root so it applies to the shadow DOM map div
      const link = document.createElement('link');
      link.rel = 'stylesheet';
      link.href = MAPLIBRE_CSS;
      this._shadow.insertBefore(link, this._shadow.firstChild);

      this._loadDeps();
    }

    disconnectedCallback() {
      if (this._map) {
        this._map.remove();
        this._map = null;
      }
    }

    _loadDeps() {
      Promise.resolve()
        .then(() => window.pmtiles    ? null : loadScript(PMTILES_JS))
        .then(() => window.maplibregl ? null : loadScript(MAPLIBRE_JS))
        .then(() => this._initMap());
    }

    _makeTravelColor(prop) {
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

    _makeHospitalIcon(label, color) {
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

    _initMap() {
      const pmtilesDir    = this.getAttribute('pmtiles-dir')   || 'pmtiles';
      const hospitalsSrc  = this.getAttribute('hospitals-src') || 'hospitals.geojson';
      const mapContainer  = this._shadow.getElementById('map');
      const panel         = this._shadow.getElementById('hex-info-panel');
      const content       = this._shadow.getElementById('hex-info-content');

      // Register PMTiles protocol once
      if (!maplibregl._pmtilesRegistered) {
        const protocol = new pmtiles.Protocol();
        maplibregl.addProtocol('pmtiles', protocol.tile);
        maplibregl._pmtilesRegistered = true;
      }

      const map = new maplibregl.Map({
        container: mapContainer,
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
      this._map = map;

      map.addControl(new maplibregl.NavigationControl(), 'top-right');

      let currentProp = 'avg_travel_any';

      map.on('load', () => {
        map.addImage('hospital-1', this._makeHospitalIcon('1', '#6b9ec7'));
        map.addImage('hospital-2', this._makeHospitalIcon('2', '#9b7dbf'));
        map.addImage('hospital-3', this._makeHospitalIcon('3', '#c4744d'));

        map.addSource('hexagon-5km',  { type: 'vector', url: `pmtiles://${pmtilesDir}/hex_5km.pmtiles`  });
        map.addSource('hexagon-1km',  { type: 'vector', url: `pmtiles://${pmtilesDir}/hex_1km.pmtiles`  });
        map.addSource('hexagon-100m', { type: 'vector', url: `pmtiles://${pmtilesDir}/hex_100m.pmtiles` });
        map.addSource('hospitals', { type: 'geojson', data: hospitalsSrc });

        const addHexLayers = (id, source, sourceLayer, minZoom, maxZoom) => {
          map.addLayer({
            id: `${id}-fill`, type: 'fill', source, 'source-layer': sourceLayer,
            minzoom: minZoom, maxzoom: maxZoom,
            paint: { 'fill-color': this._makeTravelColor(currentProp), 'fill-opacity': 0.75 },
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
          layout: {
            'icon-image': ['match', ['to-string', ['get', 'level']], '1', 'hospital-1', '2', 'hospital-2', 'hospital-3'],
            'icon-allow-overlap': true,
            'icon-ignore-placement': true,
          },
        });

        map.addLayer({ id: 'carto-labels-layer', type: 'raster', source: 'carto-labels' });

        // Hover: side panel
        const hexFillLayers = ['hexagon-5km-fill', 'hexagon-1km-fill', 'hexagon-100m-fill'];
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

      // Layer control buttons
      const propMap = { any: 'avg_travel_any', l1: 'avg_travel_l1', l2: 'avg_travel_l2', l3: 'avg_travel_l3' };
      const fillLayers = ['hexagon-5km-fill', 'hexagon-1km-fill', 'hexagon-100m-fill'];

      this._shadow.querySelectorAll('.map-btn').forEach(btn => {
        btn.addEventListener('click', () => {
          const layer = btn.dataset.layer;
          currentProp = propMap[layer];
          const color = this._makeTravelColor(currentProp);
          fillLayers.forEach(id => map.setPaintProperty(id, 'fill-color', color));
          this._shadow.querySelectorAll('.map-btn').forEach(b => b.classList.toggle('active', b === btn));
        });
      });

      // Hospital toggle
      this._shadow.getElementById('toggle-hospitals').addEventListener('change', (e) => {
        map.setLayoutProperty('hospitals-layer', 'visibility', e.target.checked ? 'visible' : 'none');
      });
    }
  }

  customElements.define('accessibility-map', AccessibilityMap);
})();
