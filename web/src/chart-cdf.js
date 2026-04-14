import { Plotly } from './plotly-loader.js';
import { dataUrl } from './data-dir.js';

export class ChartCdf extends HTMLElement {
  async connectedCallback() {
    const src = dataUrl(this.getAttribute('src') ?? 'chart-cdf.json');
    const data = await fetch(src).then(r => r.json());
    this._render(data);
  }

  _render(data) {
    let container = this.querySelector('#chart-cdf');
    if (!container) {
      container = document.createElement('div');
      container.id = 'chart-cdf';
      container.style.width = '100%';
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
      title: 'Cumulative Population Accessibility (CDF)',
      xaxis: { title: 'Travel time to nearest hospital (minutes)', range: [0, 70] },
      yaxis: { title: 'Cumulative population (%)' },
      legend: { title: { text: 'Hospital level' } },
      template: 'plotly_white',
      font: { family: '"Source Sans 3",Helvetica,sans-serif' },
      margin: { t: 50, b: 80, l: 60, r: 20 },
      shapes: [
        { type: 'line', x0: 15, x1: 15, y0: 0, y1: 100, line: { dash: 'dash', color: 'gray' } },
        { type: 'line', x0: 30, x1: 30, y0: 0, y1: 100, line: { dash: 'dash', color: 'gray' } },
      ],
      annotations: [
        { x: 15, y: 5, text: '15 min', showarrow: false, xanchor: 'left', font: { color: 'gray', size: 11 } },
        { x: 30, y: 5, text: '30 min', showarrow: false, xanchor: 'left', font: { color: 'gray', size: 11 } },
      ],
    };

    Plotly.newPlot(container, traces, layout, { responsive: true });
  }
}

customElements.define('chart-cdf', ChartCdf);
