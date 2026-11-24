import {heading, panel} from '../components/common/heading.js';
import {entries, records} from '../components/common/records.js';
import {topic} from '../constants/project.js';
import {date, esc} from '../utils/dom.js';

export function casesPage(state, identity) {
  const {spec, session, cases, runs, evidence, corrections} = state;
  const selected = cases.find(row=>row.id===identity) || cases[0];
  const operator = session.role==='operator';
  const rows = cases.map(row=>[`<a href="#cases/${row.id}" ${row.id===selected?.id?'aria-current="true"':''}>${esc(row.title)}</a>`, esc(row.author), esc(date(row.created_at))]);
  const instruction = selected ? `<h2>${esc(selected.title)}</h2><p>${esc(spec.guidance)}</p>` : '';
  const input = selected ? Object.entries(selected.payload).map(([key, value])=>{
    const label = spec.field_labels[key] || key;
    const rows = Array.isArray(value) && value.every(x=>x && typeof x === 'object' && !Array.isArray(x));
    return panel(label, rows ? entries(value.slice(0,10), spec.field_labels) + (value.length>10?`<p class="note">显示前 10 条，共 ${value.length} 条。</p>`:'') : `<pre>${esc(value)}</pre>`);
  }).join('') : '';
  const selectedCorrections = selected ? corrections.filter(row=>row.case_id===selected.id) : [];
  const correctionLog = selected ? panel('更正登记', records(['批次','原字节','更正字节','第几版','原因','经办','时间'],
    selectedCorrections.map(row=>[esc(row.batch_id), esc(row.old_size_bytes), esc(row.new_size_bytes),
      esc(row.revision), esc(row.reason), esc(row.actor), esc(date(row.created_at))]), '尚无更正，盘点为初始版本。')) : '';
  const correctionForm = selected && operator ? `<form id="correction-form" data-case="${selected.id}">
    <h2>登记字节更正</h2><p class="note">旧报告保留原文但作废；旧数试算即使晚完成也不生效。旧数交接物标记待追回。</p>
    <div class="field-grid">
      <label class="field"><span>批次编号</span><input name="batch_id" required maxlength="64" /></label>
      <label class="field"><span>更正后字节数</span><input name="new_size_bytes" type="number" min="1" step="1" required /></label>
      <label class="field"><span>原字节数（可选核对）</span><input name="old_size_bytes" type="number" min="0" step="1" /></label>
      <label class="field"><span>更正说明</span><input name="reason" required maxlength="500" /></label>
    </div>
    <div class="actions form-actions"><button>登记更正</button></div></form>` : '';
  const selectedEvidence = selected ? evidence.filter(row=>runs.some(run=>run.id===row.run_id && run.case_id===selected.id)) : [];
  const evidenceLog = selected ? panel('试算报告', records(['执行','报告状态','结论','复核'],
    selectedEvidence.map(row=>[`<a href="#evidence/${row.id}">执行 ${esc(row.run_id)}</a>`, esc(row.state==='void'?'已作废':'有效'),
      esc(row.report.summary), esc(row.reviewer || '待复核')]), '尚无试算报告。')) : '';
  return `${heading(topic.modules[0], spec.summary, operator?'<a class="button" href="#editor">建立档案</a>':'')}
    <div class="spread"><section aria-label="档案目录">${records([spec.entity_labels[0], '经办', '建立时间'], rows, '尚未建立档案。经办员可以从演示资料建立第一份。')}</section>
    <aside class="brief">${instruction || `<h2>${esc(spec.customer)}</h2>`}${selected?`<p class="note">当前盘点版本：第 ${esc(selected.revision || 1)} 版；该档案记录 ${runs.filter(row=>row.case_id===selected.id).length} 次执行。</p>`:''}${selected&&operator?`<a href="#editor/${selected.id}">复制为新档案</a>`:''}</aside></div>
    ${selected ? `<div class="spread">${correctionLog}${correctionForm}</div>${evidenceLog}` : ''}
    ${input ? `<div class="inspection">${input}</div>`:''}`;
}

export function bindCaseCorrection(state, api, update, fail) {
  const form = document.getElementById('correction-form');
  if (!form) return;
  const key = crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`;
  form.addEventListener('submit', async event=>{
    event.preventDefault();
    const button = form.querySelector('button');
    button.disabled = true;
    const data = new FormData(form);
    const oldSize = data.get('old_size_bytes');
    try {
      const result = await api(`/cases/${form.dataset.case}/corrections`, {method:'POST', data:{
        request_key:key,
        batch_id:String(data.get('batch_id')).trim(),
        new_size_bytes:Number(data.get('new_size_bytes')),
        old_size_bytes:oldSize ? Number(oldSize) : null,
        reason:String(data.get('reason')).trim()
      }});
      if (result.duplicate) fail(new Error('该更正此前已登记，未重复登记。'));
      await update();
    } catch (error) { fail(error); }
    finally { button.disabled = false; }
  });
}
