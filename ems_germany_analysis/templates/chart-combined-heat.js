(function () {
  const PLOTLY_JS = 'https://cdn.plot.ly/plotly-3.0.1.min.js';

  class ChartCombinedHeat extends HTMLElement {
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

      if (!data) {
        container.innerHTML = '<p style="padding:1rem;font-style:italic;color:#8c8880;">State-level data not available.</p>';
        return;
      }

      const traces = [{
        type: 'heatmap',
        x: data.age_groups,
        y: data.states,
        z: data.z,
        colorscale: [
          [0,   '#dce8f5'],
          [0.33, '#2563a8'],
          [1,   '#1a1945'],
        ],
        zmin: 0,
        zmax: 45,
        colorbar: {
          title: 'min',
          thickness: 12,
          len: 0.8,
        },
        hovertemplate: '<b>%{y}</b><br>Age: %{x}<br>Mean travel: %{z:.1f} min<extra></extra>',
      }];

      const layout = {
        xaxis: { title: 'Age group', side: 'bottom' },
        yaxis: { automargin: true },
        template: 'plotly_white',
        font: { family: 'Source Serif 4, Georgia, serif', size: 12 },
        margin: { t: 20, b: 60, l: 160, r: 80 },
      };

      Plotly.newPlot(container, traces, layout, { responsive: true });
    }
  }

  customElements.define('chart-combined-heat', ChartCombinedHeat);
})();
