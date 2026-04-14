import { Plotly } from './plotly-loader.js';
import { dataUrl } from './data-dir.js';
import { renderStatsTable } from './stats-table.js';

const CATEGORY_LABELS = { 'any': 'Any Hospital', 'l23': 'Level 2 or 3' };
const CATEGORY_COLORS = { 'any': '#2563a8', 'l23': '#c0392b' };
const THRESHOLD_LABELS = { '15': '≤ 15 min', '30': '≤ 30 min', '60': '≤ 60 min' };

function selectStyle() {
  return [
    'font-family:"Source Sans 3",Helvetica,sans-serif',
    'font-size:0.8em',
    'color:#586e75',
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
    'font-size:0.8em',
    'color:#93a1a1',
    'letter-spacing:0.04em',
    'text-transform:uppercase',
  ].join(';');
}

export class ChartBlCoverage extends HTMLElement {
  connectedCallback() {
    this._category  = 'any';
    this._threshold = '30';
    this._data      = null;
    this._init();
  }

  async _init() {
    const src = dataUrl(this.getAttribute('src') ?? 'chart-bl-coverage.json');
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
    if (this.querySelector('.cbc-wrapper')) return;

    const wrapper = document.createElement('div');
    wrapper.className = 'cbc-wrapper';
    wrapper.style.cssText = 'display:flex;flex-direction:column;width:100%;';

    const controls = document.createElement('div');
    controls.style.cssText = 'margin:10px;display:flex;align-items:center;gap:14px;justify-content:flex-end;flex-wrap:wrap;';

    const catLabel = document.createElement('label');
    catLabel.textContent = 'Hospital type:';
    catLabel.style.cssText = labelStyle();

    const catSelect = document.createElement('select');
    catSelect.style.cssText = selectStyle();
    Object.entries(CATEGORY_LABELS).forEach(([val, text]) => {
      const opt = document.createElement('option');
      opt.value = val;
      opt.textContent = text;
      if (val === this._category) opt.selected = true;
      catSelect.appendChild(opt);
    });
    catSelect.addEventListener('change', (e) => {
      this._category = e.target.value;
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
    });

    controls.append(catLabel, catSelect, thrLabel, thrSelect);

    const chartDiv = document.createElement('div');
    chartDiv.className = 'cbc-chart';
    chartDiv.style.cssText = 'width:100%;min-height:420px;';

    const statsDiv = document.createElement('div');
    statsDiv.className = 'cbc-stats';
    statsDiv.style.cssText = [
      'margin-top:0',
      'padding:8px 16px 12px',
      'border-top:1px solid #dedad2',
    ].join(';');

    wrapper.append(controls, chartDiv, statsDiv);
    this.appendChild(wrapper);
  }

  _sortedData() {
    const vals = this._data[this._category][this._threshold];
    const states = this._data.states;
    const pairs = states.map((s, i) => [s, vals[i]]);
    pairs.sort((a, b) => a[1] - b[1]);
    return { states: pairs.map(p => p[0]), vals: pairs.map(p => p[1]) };
  }

  _renderChart() {
    const chartDiv = this.querySelector('.cbc-chart');
    if (!chartDiv || !this._data) return;

    const { states, vals } = this._sortedData();
    const color = CATEGORY_COLORS[this._category];

    const traces = [{
      type: 'bar',
      orientation: 'h',
      x: vals,
      y: states,
      text: vals.map(v => v != null ? v.toFixed(1) + '%' : ''),
      textposition: 'outside',
      cliponaxis: false,
      textfont: { size: 11, color: '#586e75' },
      marker: { color, opacity: 0.82 },
      hovertemplate: '<b>%{y}</b><br>%{x:.1f}% within threshold<extra></extra>',
    }];

    const layout = {
      xaxis: {
        title: 'Population within threshold (%)',
        range: [0, 108],
        ticksuffix: '%',
        zeroline: false,
        tickfont: { size: 12, color: '#586e75' },
      },
      yaxis: { automargin: true, tickfont: { size: 12, color: '#4a4840' } },
      template: 'plotly_white',
      font: { family: "'Source Sans 3', Helvetica, sans-serif", size: 13 },
      margin: { t: 20, b: 60, l: 180, r: 80 },
      showlegend: false,
      height: 520,
    };

    if (chartDiv._plotlyRendered) {
      Plotly.react(chartDiv, traces, layout, { displayModeBar: false });
    } else {
      Plotly.newPlot(chartDiv, traces, layout, { responsive: true, displayModeBar: false });
      chartDiv._plotlyRendered = true;
    }
  }

  _renderStats() {
    const statsDiv = this.querySelector('.cbc-stats');
    if (!statsDiv || !this._data) return;

    const stats = this._data.stats ?? {};
    const fmt   = (v, suf) => v != null ? `${v.toFixed(1)}${suf}` : '—';
    const anyS  = stats.any ?? {};
    const l23S  = stats.l23 ?? {};

    statsDiv.innerHTML = renderStatsTable(
      { label: 'Any Hospital', color: '#2563a8' },
      { label: 'Level 2 or 3', color: '#c0392b' },
      [
        { metric: 'Median travel time',   left: fmt(anyS.median, ' min'),        right: fmt(l23S.median, ' min')        },
        { metric: 'Population > 30 min',  left: fmt(anyS.underserved_pct, '%'),  right: fmt(l23S.underserved_pct, '%')  },
      ],
    );
  }
}

customElements.define('chart-bl-coverage', ChartBlCoverage);
