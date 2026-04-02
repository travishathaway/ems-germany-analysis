(function () {
  const PLOTLY_JS = 'https://cdn.plot.ly/plotly-3.0.1.min.js';

  class ChartEquity extends HTMLElement {
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
      let container = this.querySelector('#chart-equity');
      if (!container) {
        container = document.createElement('div');
        container.id = 'chart-equity';
        container.style.width = '100%';
        this.appendChild(container);
      }

      const traces = data.groups.map(g => ({
        type: 'bar',
        name: g.name,
        x: g.x,
        y: g.y,
        marker: { color: g.color },
        text: g.y.map(v => v.toFixed(1) + '%'),
        textposition: 'outside',
      }));

      const layout = {
        title: 'Equity Analysis: Access to Level 3 Hospitals by Age Group',
        xaxis: { title: 'Travel time threshold' },
        yaxis: { title: 'Population covered (%)', range: [0, 110] },
        barmode: 'group',
        legend: { title: { text: 'Age group' } },
        template: 'plotly_white',
        font: { family: 'Arial, sans-serif' },
        margin: { t: 50, b: 80, l: 60, r: 20 },
      };

      Plotly.newPlot(container, traces, layout, { responsive: true });
    }
  }

  customElements.define('chart-equity', ChartEquity);
})();
