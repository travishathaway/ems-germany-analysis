(function () {
  const PLOTLY_JS = 'https://cdn.plot.ly/plotly-3.0.1.min.js';

  class ChartSidebarHist extends HTMLElement {
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
      let container = this.querySelector('.chart-container');
      if (!container) {
        container = document.createElement('div');
        container.className = 'chart-container';
        container.style.cssText = 'width:100%;height:100%;';
        this.appendChild(container);
      }

      const traces = data.series.map(s => ({
        type: 'bar',
        name: s.name,
        x: s.x,
        y: s.y,
        marker: { color: s.color },
      }));

      const layout = {
        xaxis: { title: 'Travel time (min)', tickangle: -45, tickfont: { size: 9 } },
        yaxis: { title: '% population', tickfont: { size: 9 } },
        template: 'plotly_white',
        font: { family: 'Source Code Pro, monospace', size: 10 },
        margin: { t: 10, b: 60, l: 45, r: 10 },
        showlegend: false,
      };

      Plotly.newPlot(container, traces, layout, { responsive: true });
    }
  }

  customElements.define('chart-sidebar-hist', ChartSidebarHist);
})();
