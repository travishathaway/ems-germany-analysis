(function () {
  const PMTILES_JS  = 'https://unpkg.com/pmtiles@3.2.0/dist/pmtiles.js';
  const MAPLIBRE_JS = 'https://unpkg.com/maplibre-gl@4/dist/maplibre-gl.js';
  const MAPLIBRE_CSS = 'https://unpkg.com/maplibre-gl@4/dist/maplibre-gl.css';
  const PLOTLY_JS = 'https://cdn.plot.ly/plotly-3.0.1.min.js';

  /* ── Inject MapLibre CSS into document head ───────────────────── */
  function injectMaplibreCSS() {
    if (document.querySelector(`link[href="${MAPLIBRE_CSS}"]`)) return;
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = MAPLIBRE_CSS;
    document.head.appendChild(link);
  }

  /* ── Build map controls HTML inside the container ────────────── */
  const CONTROLS_HTML = `
    <style>
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
      .legend-grad { width: 130px; height: 12px; border-radius: 3px; background: linear-gradient(to right, #1a9641, #a6d96a, #ffffbf, #fdae61, #d7191c); }
      .legend-labels { display: flex; justify-content: space-between; font-size: 0.78rem; color: #666; }
      .panel-section-title { font-weight: 600; color: #1a3a5c; margin: 10px 0 4px; font-size: 0.82rem; text-transform: uppercase; letter-spacing: 0.05em; }
      .panel-table { width: 100%; border-collapse: collapse; font-size: 0.82rem; }
      .panel-table td { padding: 3px 0; }
      .panel-table td:last-child { text-align: right; font-weight: 500; }
    </style>
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
  `;

  /* Unused legacy template block kept for reference only */
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

  function initMap(wrapper) {
    const pmtilesDir   = wrapper.dataset.pmtilesDir   || 'pmtiles';
    const hospitalsSrc = wrapper.dataset.hospitalsSrc || 'hospitals.geojson';

    // Inject controls HTML and a #map div into the wrapper
    wrapper.style.position = 'relative';
    wrapper.style.overflow = 'hidden';
    wrapper.innerHTML = CONTROLS_HTML + '<div id="map" style="position:absolute;inset:0;"></div>';

    const mapEl   = wrapper.querySelector('#map');
    const content = wrapper.querySelector('#hex-info-content');

    // Also update sidebar info card if it exists in the document
    const infoAny = document.getElementById('info-any');
    const infoL1  = document.getElementById('info-l1');
    const infoL2  = document.getElementById('info-l2');
    const infoL3  = document.getElementById('info-l3');
    const infoPop = document.getElementById('info-pop');

    if (!maplibregl._pmtilesRegistered) {
      const protocol = new pmtiles.Protocol();
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

    let currentProp = 'avg_travel_any';

    // Cluster state — declared here so the hospital toggle can access them
    const HOSP_COLORS = ['#6b9ec7', '#9b7dbf', '#c4744d'];
    const clusterMarkers = {};
    let clusterMarkersOnScreen = {};
    let hospitalsVisible = true;
    let updateClusterMarkers = () => {};   // replaced after map load

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
          paint: { 'fill-color': makeTravelColor(currentProp), 'fill-opacity': 0.75 },
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

      // Individual (unclustered) hospital icons
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

      // ── Cluster donut markers ──────────────────────────────────
      function donutSegment(start, end, r, r0, color) {
        if (end - start === 1) end -= 0.00001;
        const a0 = 2 * Math.PI * (start - 0.25);
        const a1 = 2 * Math.PI * (end - 0.25);
        const x0 = Math.cos(a0), y0 = Math.sin(a0);
        const x1 = Math.cos(a1), y1 = Math.sin(a1);
        const largeArc = end - start > 0.5 ? 1 : 0;
        return `<path d="M ${r + r0 * x0} ${r + r0 * y0} L ${r + r * x0} ${r + r * y0} A ${r} ${r} 0 ${largeArc} 1 ${r + r * x1} ${r + r * y1} L ${r + r0 * x1} ${r + r0 * y1} A ${r0} ${r0} 0 ${largeArc} 0 ${r + r0 * x0} ${r + r0 * y0}" fill="${color}" />`;
      }

      function createClusterDonut(props) {
        const counts = [props.lvl1 || 0, props.lvl2 || 0, props.lvl3 || 0];
        const total  = counts.reduce((a, b) => a + b, 0);
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
        svg += `</svg>`;

        const el = document.createElement('div');
        el.style.cursor = 'pointer';
        el.innerHTML = svg;
        el.title = `${total} hospitals (L1: ${counts[0]}, L2: ${counts[1]}, L3: ${counts[2]})`;
        return el;
      }

      updateClusterMarkers = function () {
        if (!hospitalsVisible) return;
        const newMarkers = {};
        const features = map.querySourceFeatures('hospitals');

        for (const feature of features) {
          const props = feature.properties;
          if (!props.cluster) continue;
          const id = props.cluster_id;

          let marker = clusterMarkers[id];
          if (!marker) {
            marker = clusterMarkers[id] = new maplibregl.Marker({ element: createClusterDonut(props) })
              .setLngLat(feature.geometry.coordinates);
          }
          newMarkers[id] = marker;
          if (!clusterMarkersOnScreen[id]) marker.addTo(map);
        }

        for (const id in clusterMarkersOnScreen) {
          if (!newMarkers[id]) clusterMarkersOnScreen[id].remove();
        }
        clusterMarkersOnScreen = newMarkers;
      }

      map.on('data', (e) => {
        if (e.sourceId !== 'hospitals' || !e.isSourceLoaded) return;
        map.on('move', updateClusterMarkers);
        map.on('moveend', updateClusterMarkers);
        updateClusterMarkers();
      });

      // Hover: floating panel + sidebar info card
      const hexFillLayers = ['hexagon-5km-fill', 'hexagon-1km-fill', 'hexagon-100m-fill'];
      hexFillLayers.forEach(layerId => {
        map.on('mousemove', layerId, (e) => {
          map.getCanvas().style.cursor = 'pointer';
          const p = e.features[0].properties;
          const fmt = (v) => (v == null || v >= 900) ? 'n/a' : v.toFixed(1) + ' min';

          // Update sidebar info card in the main document
          if (infoAny) infoAny.textContent = fmt(p.avg_travel_any);
          if (infoL1)  infoL1.textContent  = fmt(p.avg_travel_l1);
          if (infoL2)  infoL2.textContent  = fmt(p.avg_travel_l2);
          if (infoL3)  infoL3.textContent  = fmt(p.avg_travel_l3);
          if (infoPop) infoPop.textContent = (p.total_population || 0).toLocaleString();

          var data = [{
            type: "pie",
            values: [p.pop_under18, p.pop_18to29, p.pop_30to49, p.pop_50to64, p.pop_65plus],
            labels: ["0-17", "18-29", "30-49", "50-64", "65+"],
            textinfo: "label+percent",
            textposition: "outside",
            automargin: "top",
            marker: {
              colors: ['#363432', '#196774', '#90A19D', '#F0941F', '#EF6024']
            }
          }]

          var layout = {
            height: 200,
            width: 200,
            margin: {"t": 45, "b": 45, "l": 45, "r": 45},
            showlegend: false
          }

          Plotly.newPlot('demographic-pie-chart-cell', data, layout, {staticPlot: true})
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

    wrapper.querySelectorAll('.map-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const layer = btn.dataset.layer;
        currentProp = propMap[layer];
        const color = makeTravelColor(currentProp);
        fillLayers.forEach(id => map.setPaintProperty(id, 'fill-color', color));
        wrapper.querySelectorAll('.map-btn').forEach(b => b.classList.toggle('active', b === btn));
      });
    });

    wrapper.querySelector('#toggle-hospitals').addEventListener('change', (e) => {
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

  /* ── Bootstrap on DOMContentLoaded ────────────────────────���──── */
  document.addEventListener('DOMContentLoaded', () => {
    const wrapper = document.getElementById('maplibre-container');
    if (!wrapper) return;

    injectMaplibreCSS();

    Promise.resolve()
      .then(() => window.pmtiles    ? null : loadScript(PMTILES_JS))
      .then(() => window.maplibregl ? null : loadScript(MAPLIBRE_JS))
      .then(() => loadScript(PLOTLY_JS))
      .then(() => initMap(wrapper));
  });
})();
