(function () {
  const PLOTLY_JS = 'https://cdn.plot.ly/plotly-3.0.1.min.js';

  const AGE_COLORS = {
    'Any Hospital':   '#2563a8',
    'Level 2 or 3':   '#c0392b',
  };

  const THRESHOLD_LABELS = { '15': '≤ 15 min', '30': '≤ 30 min', '60': '≤ 60 min' };

  function _selectStyle() {
    return [
      'font-family:"Source Sans 3",Helvetica,sans-serif',
      'font-size:0.45em',
      'color:#586e75',
      'background:#fdf6e3',
      'border:1px solid #93a1a1',
      'border-radius:4px',
      'padding:2px 20px 2px 7px',
      'cursor:pointer',
      'appearance:none',
      '-webkit-appearance:none',
      'background-image:url(\'data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="10" height="6"><polyline points="0,0 5,5 10,0" fill="none" stroke="%2393a1a1" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>\')',
      'background-repeat:no-repeat',
      'background-position:right 6px center',
      'outline:none',
    ].join(';');
  }

  function _labelStyle() {
    return [
      'font-family:"Source Sans 3",Helvetica,sans-serif',
      'font-size:0.45em',
      'color:#93a1a1',
      'letter-spacing:0.04em',
      'text-transform:uppercase',
    ].join(';');
  }

  class ChartAgeLevelBl extends HTMLElement {
    connectedCallback() {
      this._region    = 'All Germany';
      this._threshold = '30';
      this._data      = null;
      this._loadPlotly();
    }

    _loadPlotly() {
      if (window.Plotly) { this._fetchAndRender(); return; }
      const existing = document.querySelector(`script[src="${PLOTLY_JS}"]`);
      if (existing) { existing.addEventListener('load', () => this._fetchAndRender()); return; }
      const s = document.createElement('script');
      s.src = PLOTLY_JS;
      s.onload = () => this._fetchAndRender();
      document.head.appendChild(s);
    }

    async _fetchAndRender() {
      const src = this.getAttribute('src');
      if (!src) return;
      try {
        this._data = await fetch(src).then(r => r.json());
      } catch (e) {
        this.innerHTML = '<p style="padding:1rem;color:#c0392b;">Failed to load chart data.</p>';
        return;
      }
      this._buildUI();
      this._renderChart();
      this._renderStats();
    }

    _buildUI() {
      if (this.querySelector('.calbl-wrapper')) return;

      const wrapper = document.createElement('div');
      wrapper.className = 'calbl-wrapper';
      wrapper.style.cssText = 'display:flex;flex-direction:column;width:100%;';

      // ── Controls row ──────────────────────────────────────────────────────
      const controls = document.createElement('div');
      controls.style.cssText = 'margin-bottom:8px;display:flex;align-items:center;gap:14px;justify-content:flex-end;flex-wrap:wrap;';

      // Region dropdown
      const regionLabel = document.createElement('label');
      regionLabel.textContent = 'Region:';
      regionLabel.style.cssText = _labelStyle();

      const regionSelect = document.createElement('select');
      regionSelect.style.cssText = _selectStyle();

      const regions = Object.keys(this._data.data);
      // Put "All Germany" first
      const sorted = ['All Germany', ...regions.filter(r => r !== 'All Germany').sort()];
      sorted.forEach(r => {
        const opt = document.createElement('option');
        opt.value = r;
        opt.textContent = r;
        if (r === this._region) opt.selected = true;
        regionSelect.appendChild(opt);
      });
      regionSelect.addEventListener('change', (e) => {
        this._region = e.target.value;
        this._renderChart();
        this._renderStats();
      });

      // Threshold dropdown
      const thrLabel = document.createElement('label');
      thrLabel.textContent = 'Threshold:';
      thrLabel.style.cssText = _labelStyle();

      const thrSelect = document.createElement('select');
      thrSelect.style.cssText = _selectStyle();
      Object.entries(THRESHOLD_LABELS).forEach(([val, text]) => {
        const opt = document.createElement('option');
        opt.value = val;
        opt.textContent = text;
        if (val === this._threshold) opt.selected = true;
        thrSelect.appendChild(opt);
      });
      thrSelect.addEventListener('change', (e) => {
        this._threshold = e.target.value;
        this._renderChart();
      });

      controls.append(regionLabel, regionSelect, thrLabel, thrSelect);

      // ── Chart container ───────────────────────────────────────────────────
      const chartDiv = document.createElement('div');
      chartDiv.className = 'calbl-chart';
      chartDiv.style.cssText = 'width:100%;min-height:340px;';

      // ── Stats panel ───────────────────────────────────────────────────────
      const statsDiv = document.createElement('div');
      statsDiv.className = 'calbl-stats';
      statsDiv.style.cssText = [
        'display:grid',
        'grid-template-columns:1fr 1fr',
        'gap:12px',
        'margin-top:16px',
        'padding:12px 0 4px',
        'border-top:1px solid #dedad2',
      ].join(';');

      wrapper.append(controls, chartDiv, statsDiv);
      this.appendChild(wrapper);
    }

    _buildTraces() {
      const regionData = this._data.data[this._region];
      if (!regionData) return [];
      const thr = regionData[this._threshold];
      if (!thr) return [];
      const ageGroups = this._data.age_groups;

      return [
        {
          type: 'bar',
          name: 'Any Hospital',
          x: ageGroups,
          y: thr.any,
          text: thr.any.map(v => v.toFixed(1) + '%'),
          textposition: 'inside',
          textfont: { color: '#ffffff', size: 12, weight: 'bold' },
          insidetextanchor: 'middle',
          marker: { color: AGE_COLORS['Any Hospital'] },
        },
        {
          type: 'bar',
          name: 'Level 2 or 3',
          x: ageGroups,
          y: thr.l23,
          text: thr.l23.map(v => v.toFixed(1) + '%'),
          textposition: 'inside',
          textfont: { color: '#ffffff', size: 12, weight: 'bold' },
          insidetextanchor: 'middle',
          marker: { color: AGE_COLORS['Level 2 or 3'] },
        },
      ];
    }

    _buildLayout() {
      return {
        xaxis: { title: 'Age group' },
        yaxis: {
          automargin: true,
          ticklabelstandoff: 10,
          ticksuffix: '%',
          range: [0, 105],
          tickfont: { size: 14, weight: 'bold', color: '#586e75' },
        },
        barmode: 'group',
        legend: {
          orientation: 'h',
          yanchor: 'bottom',
          y: 1.02,
          xanchor: 'right',
          x: 1,
        },
        template: 'plotly_white',
        font: {
          family: "'Source Sans 3', Helvetica, sans-serif",
          size: 14,
        },
        margin: { t: 40, b: 60, l: 60, r: 20 },
      };
    }

    _renderChart() {
      const chartDiv = this.querySelector('.calbl-chart');
      if (!chartDiv) return;
      const traces = this._buildTraces();
      if (chartDiv._plotlyRendered) {
        Plotly.react(chartDiv, traces, this._buildLayout(), { displayModeBar: false });
      } else {
        Plotly.newPlot(chartDiv, traces, this._buildLayout(), { responsive: true, displayModeBar: false });
        chartDiv._plotlyRendered = true;
      }
    }

    _renderStats() {
      const statsDiv = this.querySelector('.calbl-stats');
      if (!statsDiv) return;

      const regionData = this._data.data[this._region];
      const stats = regionData && regionData.stats ? regionData.stats : null;

      const cardStyle = [
        'background:#f8f7f4',
        'border:1px solid #dedad2',
        'border-radius:6px',
        'padding:12px 16px',
      ].join(';');

      const titleStyle = [
        'font-family:"Source Sans 3",Helvetica,sans-serif',
        'font-size:0.75rem',
        'font-weight:700',
        'letter-spacing:0.04em',
        'text-transform:uppercase',
        'color:#8c8880',
        'margin-bottom:8px',
      ].join(';');

      const metricStyle = [
        'display:flex',
        'justify-content:space-between',
        'align-items:baseline',
        'margin-bottom:4px',
      ].join(';');

      const labelStyle = [
        'font-family:"Source Sans 3",Helvetica,sans-serif',
        'font-size:0.8rem',
        'color:#4a4840',
      ].join(';');

      const valueStyle = [
        'font-family:"Source Serif 4",Georgia,serif',
        'font-size:1.1rem',
        'font-weight:700',
        'color:#1a1915',
      ].join(';');

      const formatMedian = (s) => s && s.median != null ? `${s.median.toFixed(1)} min` : '—';
      const formatUnderserved = (s) => s && s.underserved_pct != null ? `${s.underserved_pct.toFixed(1)}%` : '—';

      statsDiv.innerHTML = `
        <div style="${cardStyle}">
          <div style="${titleStyle}; color:#2563a8;">Any Hospital</div>
          <div style="${metricStyle}">
            <span style="${labelStyle}">Median travel time</span>
            <span style="${valueStyle}; color:#2563a8;">${formatMedian(stats && stats.any)}</span>
          </div>
          <div style="${metricStyle}">
            <span style="${labelStyle}">Population &gt; 30 min</span>
            <span style="${valueStyle}; color:#2563a8;">${formatUnderserved(stats && stats.any)}</span>
          </div>
        </div>
        <div style="${cardStyle}">
          <div style="${titleStyle}; color:#c0392b;">Level 2 or 3</div>
          <div style="${metricStyle}">
            <span style="${labelStyle}">Median travel time</span>
            <span style="${valueStyle}; color:#c0392b;">${formatMedian(stats && stats.l23)}</span>
          </div>
          <div style="${metricStyle}">
            <span style="${labelStyle}">Population &gt; 30 min</span>
            <span style="${valueStyle}; color:#c0392b;">${formatUnderserved(stats && stats.l23)}</span>
          </div>
        </div>
      `;
    }
  }

  customElements.define('chart-age-level-bl', ChartAgeLevelBl);
})();
