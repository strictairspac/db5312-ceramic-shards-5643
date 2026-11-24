import {heading, panel} from '../components/common/heading.js';
import {records} from '../components/common/records.js';
import {evidenceBadge, handoverBadge} from '../components/common/status.js';
import {date, esc} from '../utils/dom.js';
import {topic} from '../constants/project.js';
import {handoverStatusLabels} from '../constants/workflow.js';

const filters = ['available', 'handed_over', 'pending_recovery', 'recovered'];

export function handoversPage(state) {
  const rows = state.handovers.map(row=>[
    `<a href="#evidence/${row.id}">证据 ${esc(row.id)}</a>`,
    esc(row.title || ''),
    handoverBadge(row.handover_status),
    evidenceBadge(row.state),
    esc(row.summary || ''),
    esc(row.handover_actor || '—'),
    esc(date(row.handovered_at))
  ]);
  const counts = `<div><dt>全部</dt><dd data-filter="all">${state.handovers.length}</dd></div>` + filters.map(key=>{
    const total = state.handovers.filter(row=>row.handover_status===key).length;
    return `<div><dt><button class="linkish" data-filter="${key}">${esc(handoverStatusLabels[key])}</button></dt><dd>${total}</dd></div>`;
  }).join('');
  const pending = state.handovers.filter(row=>row.handover_status==='pending_recovery');
  const recovery = pending.length && state.session.role==='operator'
    ? panel('待追回交接', records(['证据','档案','状态','待追回时间'], pending.map(row=>[
        `<a href="#evidence/${row.id}">证据 ${esc(row.id)}</a>`, esc(row.title), handoverBadge(row.handover_status),
        esc(date(row.handover_updated_at))])) +
        '<p class="note">确认旧数交接物已收回后，逐条登记追回。</p>' +
        pending.map(row=>`<form class="recover-form" data-id="${row.handover_id}"><label>追回说明<input name="note" maxlength="500" placeholder="旧数交接物已收回" /></label><button class="secondary">登记追回</button></form>`).join('')
      )
    : '';
  const table = `<div id="handover-table">${records(['证据','档案','交接状态','报告状态','结论','经办','交接时间'], rows, '尚无交接记录。')}</div>`;
  return `${heading(topic.modules[4], '按报告状态查看可交接、已交接与待追回的交接物。')}
    <dl class="metrics">${counts}</dl>
    ${recovery}
    ${panel('交接记录', table)}`;
}

export function bindHandovers(api, update, fail) {
  document.querySelectorAll('[data-filter]').forEach(button=>{
    button.addEventListener('click', event=>{
      event.preventDefault();
      const key = button.dataset.filter;
      document.querySelectorAll('#handover-table tbody tr').forEach(row=>{
        const status = row.querySelector('[data-state]')?.dataset.state;
        row.hidden = key !== 'all' && status !== key;
      });
    });
  });
  document.querySelectorAll('.recover-form').forEach(form=>{
    form.addEventListener('submit', async event=>{
      event.preventDefault();
      const button = form.querySelector('button');
      button.disabled = true;
      try {
        await api(`/handovers/${form.dataset.id}/recover`, {method:'POST',
          data:{note:new FormData(form).get('note') || null}});
        await update();
      } catch (error) { fail(error); }
      finally { button.disabled = false; }
    });
  });
}
