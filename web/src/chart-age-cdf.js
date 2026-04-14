import { Plotly } from './plotly-loader.js';
import { dataUrl } from './data-dir.js';

export class ChartAgeCdf extends HTMLElement {
  async connectedCallback() {
    const src = dataUrl(this.getAttribute('src') ?? 'chart-age-cdf.json');
    const data = await fetch(src).then(r => r.json());
    this._render(data);
  }

  _render(data) {
    let container = this.querySelector('.chart-container');
    if (!container) {
      container = document.createElement('div');
      container.className = 'chart-container';
      container.style.cssText = 'width:100%;height:100%;';
      this.appendChild(container);
    }

    const traces = data.series.map(s => ({
      type: 'scatter',
      mode: 'lines',
      name: s.name,
      x: s.x,
      y: s.y,
      line: { color: s.color, width: 2 },
    }));

    const layout = {
      xaxis: { title: 'Travel time to nearest hospital (minutes)', range: [0, 90] },
      yaxis: { title: 'Cumulative population (%)' },
      legend: { title: { text: 'Age group' } },
      template: 'plotly_white',
      font: { family: 'Source Serif 4, Georgia, serif', size: 12 },
      margin: { t: 20, b: 60, l: 60, r: 20 },
      shapes: [
        { type: 'line', x0: 15, x1: 15, y0: 0, y1: 100, line: { dash: 'dash', color: '#8c8880', width: 1 } },
        { type: 'line', x0: 30, x1: 30, y0: 0, y1: 100, line: { dash: 'dash', color: '#8c8880', width: 1 } },
      ],
      annotations: [
        { x: 15, y: 3, text: '15 min', showarrow: false, xanchor: 'left', font: { color: '#8c8880', size: 10 } },
        { x: 30, y: 3, text: '30 min', showarrow: false, xanchor: 'left', font: { color: '#8c8880', size: 10 } },
      ],
    };

    Plotly.newPlot(container, traces, layout, { responsive: true });
  }
}

customElements.define('chart-age-cdf', ChartAgeCdf);
