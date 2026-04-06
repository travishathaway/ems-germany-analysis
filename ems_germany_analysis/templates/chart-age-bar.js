(function () {
  const PLOTLY_JS = 'https://cdn.plot.ly/plotly-3.0.1.min.js';

  class ChartAgeBar extends HTMLElement {
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

      const traces = [{
        type: 'bar',
        x: data.bars.map(b => b.name),
        y: data.bars.map(b => b.mean),
        error_y: {
          type: 'data',
          array: data.bars.map(b => b.std),
          visible: true,
          color: '#8c8880',
          thickness: 1.5,
          width: 6,
        },
        marker: { color: data.bars.map(b => b.color) },
      }];

      const layout = {
        xaxis: { title: 'Age group' },
        yaxis: { title: 'Mean travel time (min)', zeroline: false },
        template: 'plotly_white',
        font: { family: 'Source Serif 4, Georgia, serif', size: 12 },
        margin: { t: 20, b: 60, l: 60, r: 20 },
        showlegend: false,
      };

      Plotly.newPlot(container, traces, layout, { responsive: true });
    }
  }

  customElements.define('chart-age-bar', ChartAgeBar);
})();
