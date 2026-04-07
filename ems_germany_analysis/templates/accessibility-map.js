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

  /* ── Build map controls HTML (left-side panel, injected into map container) */
  const CONTROLS_HTML = `
    <style>
      #map-controls {
        position: absolute;
        top: 1rem;
        left: 1rem;
        background: var(--surface, #fff);
        border: 1px solid var(--border, #dedad2);
        border-radius: var(--radius, 6px);
        box-shadow: var(--shadow, 0 1px 4px rgba(0,0,0,0.07), 0 4px 16px rgba(0,0,0,0.04));
        z-index: 10;
        width: 196px;
        font-family: var(--ff-serif, 'Source Serif 4', Georgia, serif);
        overflow: hidden;
      }
      .mc-section {
        padding: 0.55rem 0.8rem;
        border-bottom: 1px solid var(--border-light, #ebe8e0);
      }
      .mc-section:last-child { border-bottom: none; }
      .mc-label {
        font-size: 0.62rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        color: var(--ink-muted, #8c8880);
        margin-bottom: 0.35rem;
      }
      .map-btn {
        display: flex;
        align-items: center;
        gap: 6px;
        width: 100%;
        margin-bottom: 3px;
        padding: 4px 8px;
        border: 1px solid var(--border, #dedad2);
        border-radius: 4px;
        background: transparent;
        cursor: pointer;
        font-size: 0.73rem;
        font-family: var(--ff-serif, 'Source Serif 4', Georgia, serif);
        color: var(--ink, #1a1915);
        text-align: left;
        transition: background 0.12s, color 0.12s, border-color 0.12s;
      }
      .map-btn svg { flex-shrink: 0; }
      .map-btn:last-of-type { margin-bottom: 0; }
      .map-btn.active {
        background: var(--accent, #2563a8);
        color: #fff;
        border-color: var(--accent, #2563a8);
      }
      .map-btn:hover:not(.active) { background: var(--accent-light, #dce8f5); }
      .mc-toggle {
        display: flex;
        align-items: center;
        gap: 6px;
        cursor: pointer;
        font-size: 0.73rem;
        color: var(--ink-mid, #4a4840);
      }
      .mc-grad {
        height: 8px;
        border-radius: 3px;
        background: linear-gradient(to right, #1a9641, #a6d96a, #ffffbf, #fdae61, #d7191c);
        margin-bottom: 3px;
      }
      .mc-grad-labels {
        display: flex;
        justify-content: space-between;
        font-family: var(--ff-mono, 'Source Code Pro', monospace);
        font-size: 0.6rem;
        color: var(--ink-muted, #8c8880);
      }
      .mc-hosp-row {
        display: flex;
        align-items: center;
        gap: 6px;
        margin: 3px 0;
        font-size: 0.73rem;
        color: var(--ink-mid, #4a4840);
      }
      #travel-min-slider {
        width: 100%;
        margin-top: 5px;
        accent-color: var(--accent, #2563a8);
        cursor: pointer;
      }
    </style>
    <div id="map-controls">
      <div class="mc-section">
        <div class="mc-label">Show travel time to</div>
        <button class="map-btn active" data-layer="any">Any hospital</button>
        <button class="map-btn" data-layer="l1">
          <svg width="16" height="16" viewBox="0 0 20 20"><circle cx="10" cy="10" r="9" fill="#6b9ec7"/><text x="10" y="14" text-anchor="middle" font-family="Arial,sans-serif" font-size="11" font-weight="bold" fill="#fff">1</text></svg>
          <span class="map-btn-text">Basic</span>
        </button>
        <button class="map-btn" data-layer="l2">
          <svg width="16" height="16" viewBox="0 0 20 20"><circle cx="10" cy="10" r="9" fill="#9b7dbf"/><text x="10" y="14" text-anchor="middle" font-family="Arial,sans-serif" font-size="11" font-weight="bold" fill="#fff">2</text></svg>
          <span class="map-btn-text">Extended</span>
        </button>
        <button class="map-btn" data-layer="l3">
          <svg width="16" height="16" viewBox="0 0 20 20"><circle cx="10" cy="10" r="9" fill="#c4744d"/><text x="10" y="14" text-anchor="middle" font-family="Arial,sans-serif" font-size="11" font-weight="bold" fill="#fff">3</text></svg>
          <span class="map-btn-text">Comprehensive</span>
        </button>
      </div>
      <div class="mc-section">
        <div class="mc-label">Min travel time: <span id="travel-min-val">0</span> min</div>
        <input type="range" id="travel-min-slider" min="0" max="60" value="0">
      </div>
      <div class="mc-section">
        <label class="mc-toggle">
          <input type="checkbox" id="toggle-hospitals" checked>
          Show hospitals
        </label>
      </div>
      <div class="mc-section">
        <div class="mc-label">Travel time (min)</div>
        <div class="mc-grad"></div>
        <div class="mc-grad-labels"><span>0</span><span>15</span><span>30</span><span>45</span><span>60+</span></div>
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
    wrapper.innerHTML = '<div id="map" style="position:absolute;inset:0;"></div>';

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

    let currentProp  = 'avg_travel_any';
    let currentLevel = null;   // null = all levels; 1/2/3 = filter to that level
    let minTravelMin = 0;      // slider threshold in minutes (0 = no filter)

    // Cluster state — declared here so the hospital toggle can access them
    const HOSP_COLORS = ['#6b9ec7', '#9b7dbf', '#c4744d'];
    const clusterMarkers = {};
    let clusterMarkersOnScreen = {};
    let hospitalsVisible    = true;
    let updateClusterMarkers  = () => {};   // replaced after map load
    let updateHospitalFilter  = () => {};   // replaced after map load
    let updateHexFilter       = () => {};   // replaced after map load

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

      // filterLevel: null = all levels, 1/2/3 = show only that level's segment.
      // Returns null if no hospitals of the requested level exist in this cluster.
      function createClusterDonut(props, filterLevel) {
        const rawCounts = [props.lvl1 || 0, props.lvl2 || 0, props.lvl3 || 0];
        const counts = filterLevel === null
          ? rawCounts
          : rawCounts.map((c, i) => (i + 1 === filterLevel ? c : 0));
        const total  = counts.reduce((a, b) => a + b, 0);
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
        svg += `</svg>`;

        const el = document.createElement('div');
        el.style.cursor = 'pointer';
        el.innerHTML = svg;
        el.title = filterLevel === null
          ? `${total} hospitals (L1: ${rawCounts[0]}, L2: ${rawCounts[1]}, L3: ${rawCounts[2]})`
          : `${total} Level ${filterLevel} hospitals`;
        return el;
      }

      updateClusterMarkers = function () {
        if (!hospitalsVisible) return;
        const newMarkers = {};
        const features = map.querySourceFeatures('hospitals');

        for (const feature of features) {
          const props = feature.properties;
          if (!props.cluster) continue;

          // Skip clusters with none of the selected level
          if (currentLevel !== null) {
            const lvlKey = `lvl${currentLevel}`;
            if (!props[lvlKey]) continue;
          }

          const id = props.cluster_id;
          let marker = clusterMarkers[id];
          if (!marker) {
            const el = createClusterDonut(props, currentLevel);
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
      }

      updateHospitalFilter = function () {
        // Update individual hospital icon filter.
        // Use consistent legacy filter syntax throughout — mixing legacy and
        // expression syntax inside ['all', ...] is unreliable in MapLibre.
        if (currentLevel === null) {
          map.setFilter('hospitals-layer', ['!=', 'cluster', true]);
        } else {
          map.setFilter('hospitals-layer', ['all',
            ['!=', 'cluster', true],
            ['==', 'level', currentLevel],
          ]);
        }
        // Rebuild cluster donuts with new filter (clear cache first)
        for (const id in clusterMarkersOnScreen) clusterMarkersOnScreen[id].remove();
        clusterMarkersOnScreen = {};
        for (const id in clusterMarkers) delete clusterMarkers[id];
        updateClusterMarkers();
      };

      // Apply (or clear) the min-travel-time threshold filter on hex layers.
      // When minTravelMin > 0: show only cells where currentProp >= threshold
      // (and the cell has data, i.e. value < 900). When 0: clear all filters.
      const hexAllLayers = [
        'hexagon-5km-fill',  'hexagon-5km-outline',
        'hexagon-1km-fill',  'hexagon-1km-outline',
        'hexagon-100m-fill', 'hexagon-100m-outline',
      ];
      updateHexFilter = function () {
        const filter = minTravelMin === 0 ? null : ['all',
          ['>=', ['coalesce', ['get', currentProp], 999], minTravelMin],
          ['<',  ['coalesce', ['get', currentProp], 999], 900],
        ];
        hexAllLayers.forEach(id => map.setFilter(id, filter));
      };

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
          document.getElementById("demographic-pie-chart-placeholder").style.display = "none";
          Plotly.newPlot('demographic-pie-chart-cell', data, layout, {staticPlot: true})
        });
        map.on('mouseleave', layerId, () => {
          map.getCanvas().style.cursor = '';
          if (infoAny) infoAny.textContent = '—';
          if (infoL1)  infoL1.textContent  = '—';
          if (infoL2)  infoL2.textContent  = '—';
          if (infoL3)  infoL3.textContent  = '—';
          if (infoPop) infoPop.textContent  = '—';

          // Hide pie chart
          document.getElementById("demographic-pie-chart-cell").innerHTML = "";
          document.getElementById("demographic-pie-chart-placeholder").style.display = "block";
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
    const propMap  = { any: 'avg_travel_any', l1: 'avg_travel_l1', l2: 'avg_travel_l2', l3: 'avg_travel_l3' };
    const levelMap = { any: null, l1: 1, l2: 2, l3: 3 };
    const fillLayers = ['hexagon-5km-fill', 'hexagon-1km-fill', 'hexagon-100m-fill'];

    document.querySelectorAll('.map-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const layer = btn.dataset.layer;
        currentProp  = propMap[layer];
        currentLevel = levelMap[layer];
        const color = makeTravelColor(currentProp);
        fillLayers.forEach(id => map.setPaintProperty(id, 'fill-color', color));
        document.querySelectorAll('.map-btn').forEach(b => b.classList.toggle('active', b === btn));
        updateHospitalFilter();
        updateHexFilter();   // reapply threshold with updated currentProp
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
