(function () {
  const PLOTLY_JS = 'https://cdn.plot.ly/plotly-3.0.1.min.js';

  class ChartStates extends HTMLElement {
    connectedCallback() {
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
      const data = await fetch(src).then(r => r.json());
      this._render(data);
    }

    _render(data) {
      let container = this.querySelector('#chart-states');
      if (!container) {
        container = document.createElement('div');
        container.id = 'chart-states';
        container.style.width = '100%';
        this.appendChild(container);
      }

      if (!data) { container.innerHTML = '<p><em>State-level data not available.</em></p>'; return; }

      const traces = [
        {
          type: 'bar',
          orientation: 'h',
          name: 'Median (min)',
          x: data.median.map(r => r.value),
          y: data.median.map(r => r.state),
          marker: { color: '#d7191c' },
          xaxis: 'x1',
          yaxis: 'y1',
        },
        {
          type: 'bar',
          orientation: 'h',
          name: '% within 30 min',
          x: data.pct30.map(r => r.value),
          y: data.pct30.map(r => r.state),
          marker: { color: '#2c7bb6' },
          xaxis: 'x2',
          yaxis: 'y2',
        },
      ];

      const layout = {
        height: 550,
        showlegend: false,
        template: 'plotly_white',
        font: { family: 'Arial, sans-serif' },
        grid: { rows: 1, columns: 2, pattern: 'independent' },
        annotations: [
          {
            text: 'Median Travel Time to Nearest Level 3 Hospital (min)',
            xref: 'x1 domain', yref: 'y1 domain',
            x: 0.5, y: 1.05,
            showarrow: false,
            font: { size: 13 },
          },
          {
            text: '% Population within 30 min of Level 3 Hospital',
            xref: 'x2 domain', yref: 'y2 domain',
            x: 0.5, y: 1.05,
            showarrow: false,
            font: { size: 13 },
          },
        ],
        margin: { t: 60, b: 40, l: 160, r: 20 },
      };

      Plotly.newPlot(container, traces, layout, { responsive: true });
    }
  }

  customElements.define('chart-states', ChartStates);
})();
