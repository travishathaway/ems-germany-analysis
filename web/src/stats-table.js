/**
 * Renders a compact two-column summary stats table shared by chart components.
 *
 * @param {{ label: string, color: string }} leftCol
 * @param {{ label: string, color: string }} rightCol
 * @param {{ metric: string, left: string, right: string }[]} rows
 * @returns {string} HTML string
 */
export function renderStatsTable(leftCol, rightCol, rows) {
  const SEP   = `border-left:1px solid #ebe8e0;`;
  const TH    = `font-family:"Source Code Pro","Courier New",monospace;font-size:0.67rem;font-weight:600;letter-spacing:0.07em;text-transform:uppercase;padding:6px 14px 6px 0;white-space:nowrap;`;
  const TD_M  = `font-family:"Source Serif 4",Georgia,serif;font-size:0.78rem;color:#4a4840;padding:5px 14px 5px 0;white-space:nowrap;`;
  const TD_V  = `font-family:"Source Code Pro","Courier New",monospace;font-size:0.92rem;font-weight:700;padding:5px 14px 5px 14px;text-align:right;white-space:nowrap;`;
  const TD_V3 = `font-family:"Source Code Pro","Courier New",monospace;font-size:0.92rem;font-weight:700;padding:5px 14px 5px 24px;text-align:right;white-space:nowrap;`;

  const rowsHtml = rows.map(r => `
    <tr>
      <td style="${TD_M}">${r.metric}</td>
      <td style="${TD_V}color:${leftCol.color};">${r.left}</td>
      <td style="${SEP}${TD_V3}color:${rightCol.color};">${r.right}</td>
    </tr>`).join('');

  return `
    <table style="width:100%;border-collapse:collapse;table-layout:fixed;">
      <colgroup>
        <col style="width:44%">
        <col style="width:28%">
        <col style="width:28%">
      </colgroup>
      <thead>
        <tr style="border-bottom:1px solid #dedad2;">
          <th style="${TH}color:#8c8880;">Metric</th>
          <th style="${TH}color:${leftCol.color};text-align:right;">${leftCol.label}</th>
          <th style="${SEP}${TH}color:${rightCol.color};text-align:right;padding-left:24px;">${rightCol.label}</th>
        </tr>
      </thead>
      <tbody>${rowsHtml}</tbody>
    </table>`;
}
