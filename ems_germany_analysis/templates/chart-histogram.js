(function () {
  const PLOTLY_JS = 'https://cdn.plot.ly/plotly-3.0.1.min.js';

  class ChartHistogram extends HTMLElement {
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
      let container = this.querySelector('#chart-histogram');
      if (!container) {
        container = document.createElement('div');
        container.id = 'chart-histogram';
        container.style.width = '100%';
        this.appendChild(container);
      }

      const traces = data.series.map(s => ({
        type: 'bar',
        name: s.name,
        x: s.x,
        y: s.y,
        marker: { color: s.color, opacity: 0.7 },
      }));

      const layout = {
        title: 'Distribution of Travel Times (Population-Weighted)',
        xaxis: { title: 'Travel time bin (minutes)', tickangle: -45 },
        yaxis: { title: 'Share of population (%)' },
        barmode: 'group',
        legend: { title: { text: 'Hospital level' } },
        template: 'plotly_white',
        font: { family: 'Arial, sans-serif' },
        margin: { t: 50, b: 100, l: 60, r: 20 },
      };

      Plotly.newPlot(container, traces, layout, { responsive: true });
    }
  }

  customElements.define('chart-histogram', ChartHistogram);
})();
