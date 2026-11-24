import {heading, panel} from '../components/common/heading.js';
import {entries, records} from '../components/common/records.js';
import {evidenceBadge} from '../components/common/status.js';
import {topic} from '../constants/project.js';
import {date, el, esc} from '../utils/dom.js';
import {submit} from '../hooks/submit.js';

export function evidencePage(state, identity) {
  const current = state.evidence.find(row=>row.id===identity) || state.evidence[0];
  if (!current) return heading(topic.modules[3]) + '<p class="empty">执行完成后，可查看、复核和导出证据。</p>';
  const {report} = current;
  const format = new Intl.NumberFormat('zh-CN');
  const metrics = Object.entries(report.metrics).map(([label,value])=>`<div><dt>${esc(label)}</dt><dd>${esc(typeof value === 'number' ? format.format(value) : value)}</dd></div>`).join('');
  const sections = report.sections.map(x=>panel(x.title, entries(x.rows))).join('');
  const voided = current.state === 'void';
  const handover = state.handovers.find(row=>row.id===current.id);
  const handoverText = handover ? `<p>${handover.handover_status==='pending_recovery'?'旧数交接物待追回':handover.handover_status==='recovered'?'旧数交接物已追回':handover.handover_status==='handed_over'?'已于 '+date(handover.handovered_at)+' 交接':'尚未交接'}</p>` : '';
  const review = voided
    ? `<p class="error" data-testid="voided">报告作废·停止签署与交接</p><p class="note">${esc(current.void_reason || '')}</p>${handoverText}`
    : current.reviewer ? `<p data-testid="reviewed">${esc(current.reviewer)} · ${esc(date(current.reviewed_at))}</p><p>${esc(current.review_note)}</p>${handoverText}`
    : state.session.role==='reviewer'?'<form id="review-form"><label>复核意见<textarea name="note" maxlength="500" required></textarea></label><button>签署复核</button></form>'
    : '<p class="note">待复核员签署</p>';
  const canHandover = !voided && current.reviewer && state.session.role==='operator' && !handover;
  const handoverTools = canHandover ? `<form id="handover-form"><label>交接说明<input name="note" maxlength="500" placeholder="可选" /></label><button>办理交接</button></form>` : '';
  const history = state.evidence.map(row=>[`<a href="#evidence/${row.id}">执行 ${row.run_id}</a>`, evidenceBadge(row.state), esc(row.report.summary), esc(row.reviewer || '待复核')]);
  return `${heading(topic.modules[3], report.summary, `<button id="download" data-id="${current.id}">导出证据</button>`)}
    <div class="spread evidence-top"><dl class="metrics">${metrics}</dl><aside class="brief"><h2>复核签署</h2>${review}<p>${evidenceBadge(current.state)}</p>${handoverTools}<details><summary>结果校验码</summary><code class="digest">${esc(current.digest)}</code></details></aside></div>
    ${sections}<details><summary>历史证据</summary>${records(['执行','报告','结论','复核'], history)}</details>`;
}

export function bindEvidence(api, update, fail) {
  const button = document.getElementById('download');
  if (!button) return;
  const identity = button.dataset.id;
  button.addEventListener('click', async()=>{
    try {
      const response = await api(`/evidence/${identity}/download`, {response:true});
      const url = URL.createObjectURL(await response.blob());
      const link = el('a');
      link.href = url;
      link.download = `evidence-${identity}.json`;
      link.click();
      setTimeout(()=>URL.revokeObjectURL(url), 1000);
    } catch (error) { fail(error); }
  });
  submit('review-form', async data=>{
    await api(`/evidence/${identity}/review`, {method:'POST', data:{note:data.get('note')}});
    await update();
  }, fail);
  submit('handover-form', async data=>{
    await api(`/evidence/${identity}/handover`, {method:'POST', data:{note:data.get('note') || null}});
    await update();
  }, fail);
}
