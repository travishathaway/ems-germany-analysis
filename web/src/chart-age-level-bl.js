import { Plotly } from './plotly-loader.js';
import { dataUrl } from './data-dir.js';
import { renderStatsTable } from './stats-table.js';

const AGE_COLORS = {
  'Any Hospital': '#2563a8',
  'Level 2 or 3': '#c0392b',
};

const THRESHOLD_LABELS = { '15': '≤ 15 min', '30': '≤ 30 min', '60': '≤ 60 min' };

function selectStyle() {
  return [
    'font-family:"Source Sans 3",Helvetica,sans-serif',
    'font-size: 0.8em',
    'color: #586e75',
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

function labelStyle() {
  return [
    'font-family:"Source Sans 3",Helvetica,sans-serif',
    'font-size: 0.8em',
    'color: #93a1a1',
    'letter-spacing:0.04em',
    'text-transform:uppercase',
  ].join(';');
}

export class ChartAgeLevelBl extends HTMLElement {
  connectedCallback() {
    this._region    = 'All Germany';
    this._threshold = '30';
    this._data      = null;
    this._init();
  }

  async _init() {
    const src = dataUrl(this.getAttribute('src') ?? 'chart-age-level-bl.json');
    try {
      this._data = await fetch(src).then(r => r.json());
    } catch {
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

    const controls = document.createElement('div');
    controls.style.cssText = 'margin:10px;display:flex;align-items:center;gap:14px;justify-content:flex-end;flex-wrap:wrap;';

    const regionLabel = document.createElement('label');
    regionLabel.textContent = 'Region:';
    regionLabel.style.cssText = labelStyle();

    const regionSelect = document.createElement('select');
    regionSelect.style.cssText = selectStyle();
    const regions = Object.keys(this._data.data);
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

    const thrLabel = document.createElement('label');
    thrLabel.textContent = 'Threshold:';
    thrLabel.style.cssText = labelStyle();

    const thrSelect = document.createElement('select');
    thrSelect.style.cssText = selectStyle();
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
      this._renderStats();
    });

    controls.append(regionLabel, regionSelect, thrLabel, thrSelect);

    const chartDiv = document.createElement('div');
    chartDiv.className = 'calbl-chart';
    chartDiv.style.cssText = 'width:100%;min-height:340px;';

    const statsDiv = document.createElement('div');
    statsDiv.className = 'calbl-stats';
    statsDiv.style.cssText = [
      'margin-top:0',
      'padding:8px 16px 12px',
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
      legend: { orientation: 'h', yanchor: 'bottom', y: 1.02, xanchor: 'right', x: 1 },
      template: 'plotly_white',
      font: { family: "'Source Sans 3', Helvetica, sans-serif", size: 14 },
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
    const s   = regionData?.stats ?? null;
    const thr = regionData?.[this._threshold] ?? null;

    const fmt   = (v, suf) => v != null ? `${v.toFixed(1)}${suf}` : '—';
    const any   = s?.any ?? {};
    const l23   = s?.l23 ?? {};

    const stdDev = (vals) => {
      if (!vals?.length) return null;
      const mean = vals.reduce((a, b) => a + b, 0) / vals.length;
      return Math.sqrt(vals.reduce((a, b) => a + (b - mean) ** 2, 0) / vals.length);
    };

    const anyStd = stdDev(thr?.any);
    const l23Std = stdDev(thr?.l23);

    statsDiv.innerHTML = renderStatsTable(
      { label: 'Any Hospital', color: '#2563a8' },
      { label: 'Level 2 or 3', color: '#c0392b' },
      [
        { metric: 'Median travel time',   left: fmt(any.median, ' min'),        right: fmt(l23.median, ' min')        },
        { metric: 'Population > 30 min',  left: fmt(any.underserved_pct, '%'),  right: fmt(l23.underserved_pct, '%')  },
        { metric: 'Age group variance',   left: fmt(anyStd, ' pp'),             right: fmt(l23Std, ' pp')             },
      ],
    );
  }
}

customElements.define('chart-age-level-bl', ChartAgeLevelBl);
