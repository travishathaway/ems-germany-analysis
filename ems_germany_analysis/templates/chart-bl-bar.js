(function () {
  const PLOTLY_JS = 'https://cdn.plot.ly/plotly-3.0.1.min.js';

  class ChartBlBar extends HTMLElement {
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

      if (!data) { container.innerHTML = '<p style="padding:1rem;font-style:italic;color:#8c8880;">State-level data not available.</p>'; return; }

      const traces = [{
        type: 'bar',
        orientation: 'h',
        x: data.medians,
        y: data.states,
        marker: {
          color: data.medians,
          colorscale: [[0, '#dce8f5'], [0.5, '#2563a8'], [1, '#1a1945']],
          cmin: 0,
          cmax: 30,
          showscale: false,
        },
      }];

      const layout = {
        xaxis: { title: 'Median travel time (min)', zeroline: false },
        yaxis: { automargin: true },
        template: 'plotly_white',
        font: { family: 'Source Serif 4, Georgia, serif', size: 12 },
        margin: { t: 20, b: 60, l: 160, r: 20 },
        showlegend: false,
      };

      Plotly.newPlot(container, traces, layout, { responsive: true });
    }
  }

  customElements.define('chart-bl-bar', ChartBlBar);
})();
