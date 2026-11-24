import {esc} from '../../utils/dom.js';
import {evidenceStateLabels, handoverStatusLabels, statusLabels} from '../../constants/workflow.js';
export function badge(status) {
  return `<span class="status" data-state="${esc(status)}">${esc(statusLabels[status] || status)}</span>`;
}
export function evidenceBadge(state, reason='') {
  const title = reason ? ` title="${esc(reason)}"` : '';
  return `<span class="status" data-state="${esc(state)}"${title}>${esc(evidenceStateLabels[state] || state)}</span>`;
}
export function handoverBadge(status) {
  return `<span class="status" data-state="${esc(status)}">${esc(handoverStatusLabels[status] || status)}</span>`;
}
