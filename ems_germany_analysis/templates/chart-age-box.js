(function () {
  const PLOTLY_JS = 'https://cdn.plot.ly/plotly-3.0.1.min.js';

  class ChartAgeBox extends HTMLElement {
    connectedCallback() {
      this._mode = 'box';
      this._data = null;
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
      this._data = await fetch(src).then(r => r.json());
      this._buildUI();
      this._render();
    }

    _buildUI() {
      // Toggle controls
      const ctrl = document.createElement('div');
      ctrl.style.cssText = 'display:flex;justify-content:flex-end;padding:0.4rem 0.75rem;gap:0.3rem;';

      const pillGroup = document.createElement('div');
      pillGroup.className = 'pill-group';
      ['Box', 'Violin'].forEach((label, i) => {
        const btn = document.createElement('button');
        btn.className = 'pill' + (i === 0 ? ' active' : '');
        btn.textContent = label;
        btn.addEventListener('click', () => {
          pillGroup.querySelectorAll('.pill').forEach(p => p.classList.remove('active'));
          btn.classList.add('active');
          this._mode = label.toLowerCase();
          this._render();
        });
        pillGroup.appendChild(btn);
      });
      ctrl.appendChild(pillGroup);
      this.insertBefore(ctrl, this.firstChild);

      // Chart container
      const container = document.createElement('div');
      container.className = 'chart-container';
      container.style.cssText = 'width:100%;min-height:260px;';
      this.appendChild(container);
    }

    _render() {
      const container = this.querySelector('.chart-container');
      if (!container || !this._data) return;

      const traces = this._data.groups.map(g => {
        if (this._mode === 'violin') {
          return {
            type: 'violin',
            name: g.name,
            y: [g.lowerfence, g.q1, g.median, g.q3, g.upperfence],
            box: { visible: true },
            meanline: { visible: true },
            marker: { color: g.color },
            line: { color: g.color },
          };
        }
        return {
          type: 'box',
          name: g.name,
          q1: [g.q1],
          median: [g.median],
          q3: [g.q3],
          lowerfence: [g.lowerfence],
          upperfence: [g.upperfence],
          mean: [g.mean],
          marker: { color: g.color },
          line: { color: g.color },
          boxmean: 'sd',
        };
      });

      const layout = {
        yaxis: { title: 'Travel time (min)', zeroline: false },
        template: 'plotly_white',
        font: { family: 'Source Serif 4, Georgia, serif', size: 12 },
        margin: { t: 20, b: 50, l: 60, r: 20 },
        showlegend: false,
      };

      Plotly.react(container, traces, layout, { responsive: true });
    }
  }

  customElements.define('chart-age-box', ChartAgeBox);
})();
