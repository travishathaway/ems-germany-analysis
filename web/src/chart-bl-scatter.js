import { Plotly } from './plotly-loader.js';
import { dataUrl } from './data-dir.js';

export class ChartBlScatter extends HTMLElement {
  async connectedCallback() {
    const src = dataUrl(this.getAttribute('src') ?? 'chart-bl-scatter.json');
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

    if (!data || !data.points || !data.points.length) {
      container.innerHTML = '<p style="padding:1rem;font-style:italic;color:#8c8880;">State-level data not available.</p>';
      return;
    }

    const traces = [{
      type: 'scatter',
      mode: 'markers+text',
      x: data.points.map(p => p.density),
      y: data.points.map(p => p.mean),
      text: data.points.map(p => p.state),
      textposition: 'top center',
      textfont: { size: 9, color: '#4a4840' },
      marker: { color: '#2563a8', size: 10, opacity: 0.8 },
      hovertemplate: '<b>%{text}</b><br>Density: %{x:.0f} pop/cell<br>Mean travel: %{y:.1f} min<extra></extra>',
    }];

    const layout = {
      xaxis: { title: 'Population density (pop / census cell)' },
      yaxis: { title: 'Mean travel time (min)', zeroline: false },
      template: 'plotly_white',
      font: { family: 'Source Serif 4, Georgia, serif', size: 12 },
      margin: { t: 20, b: 60, l: 60, r: 20 },
      showlegend: false,
    };

    Plotly.newPlot(container, traces, layout, { responsive: true });
  }
}

customElements.define('chart-bl-scatter', ChartBlScatter);
