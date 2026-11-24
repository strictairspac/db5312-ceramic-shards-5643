import hashlib
import uuid
from copy import deepcopy

from fastapi import HTTPException
from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError

from src.config.settings import cache, engine
from src.constants.workflow import EvidenceState, HandoverStatus, Status
from src.models.tables import (audit, case_revisions, cases, corrections,
                               evidence, handovers, runs)
from src.services import domain
from src.utils.encoding import canonical
from src.utils.time import utc_time


def log(conn, actor, action, reference):
    conn.execute(audit.insert().values(actor=actor, action=action, reference=str(reference), created_at=utc_time()))


def recent(table):
    with engine.connect() as conn:
        return [dict(row) for row in conn.execute(select(table).order_by(table.c.id.desc()).limit(100)).mappings()]


def found(conn, table, identity):
    row = conn.execute(select(table).where(table.c.id == identity)).mappings().first()
    if row is None:
        raise HTTPException(404, '找不到该记录')
    return dict(row)


def make_case(title, payload, actor):
    title = title.strip()
    if not title:
        raise HTTPException(422, '档案名称不能为空')
    try:
        if len(canonical(payload)) > 512 * 1024:
            raise ValueError('业务输入超过 512 KiB')
        if callable(getattr(domain, 'validate', None)):
            domain.validate(payload)
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, str(exc)) from None
    with engine.begin() as conn:
        case_id = conn.execute(cases.insert().values(slug=uuid.uuid4().hex, title=title, payload=payload,
                               revision=1, author=actor, created_at=utc_time())).inserted_primary_key[0]
        conn.execute(case_revisions.insert().values(case_id=case_id, revision=1, payload=payload,
                                                    created_at=utc_time()))
        log(conn, actor, 'create_case', case_id)
        return dict(conn.execute(select(cases).where(cases.c.id == case_id)).mappings().first())


def case_revision(conn, case_id):
    """Current revision, defaulting legacy rows that predate versioning to 1."""
    row = conn.execute(select(cases.c.revision).where(cases.c.id == case_id)).scalar_one_or_none()
    return 1 if row is None else row


def enqueue(case_id, actor):
    with engine.begin() as conn:
        found(conn, cases, case_id)
        run_id = conn.execute(runs.insert().values(case_id=case_id, status=Status.QUEUED,
                              revision=case_revision(conn, case_id),
                              owner=actor, created_at=utc_time())).inserted_primary_key[0]
        log(conn, actor, 'enqueue', run_id)
        result = found(conn, runs, run_id)
    try:
        cache.lpush('worker:wake', 'queued')
        cache.ltrim('worker:wake', 0, 99)
    except Exception:
        # The durable database queue is polled even if Redis is temporarily unavailable.
        pass
    return result


def claim():
    ready = or_(runs.c.status == Status.QUEUED,
                and_(runs.c.status == Status.RUNNING, runs.c.started_at < utc_time(-600)))
    with engine.begin() as conn:
        run = conn.execute(select(runs.c.id, runs.c.case_id, runs.c.revision).where(ready).order_by(runs.c.id)
                           .limit(1).with_for_update(skip_locked=True)).first()
        if not run:
            return None
        token = str(uuid.uuid4())
        conn.execute(runs.update().where(runs.c.id == run.id).values(
            started_at=utc_time(), status=Status.RUNNING, attempt_token=token))
        payload = None
        if run.revision is not None:
            payload = conn.execute(select(case_revisions.c.payload).where(
                case_revisions.c.case_id == run.case_id,
                case_revisions.c.revision == run.revision)).scalar_one_or_none()
        if payload is None:
            payload = found(conn, cases, run.case_id)['payload']
        return run.id, token, payload, run.revision


def finish(run_id, token, result=None, error=None):
    digest = hashlib.sha256(canonical(result)).hexdigest() if result is not None else None
    status = Status.FAILED if error else Status.COMPLETE
    with engine.begin() as conn:
        run = conn.execute(select(runs).where(runs.c.id == run_id, runs.c.attempt_token == token,
                           runs.c.status == Status.RUNNING).with_for_update()).mappings().first()
        if run is None:
            return
        # Serialize with corrections: a report computed from a superseded revision is void on arrival.
        conn.execute(select(cases.c.id).where(cases.c.id == run.case_id).with_for_update()).first()
        current = case_revision(conn, run.case_id)
        stale = run.revision is not None and run.revision != current
        conn.execute(runs.update().where(runs.c.id == run_id).values(
            status=status, finished_at=utc_time(), error=error))
        if result is not None:
            conn.execute(evidence.insert().values(
                run_id=run_id, report=result, digest=digest, revision=run.revision,
                state=EvidenceState.VOID if stale else EvidenceState.VALID,
                voided_at=utc_time() if stale else None,
                void_reason='盘点已更正，旧数试算报告作废' if stale else None))
        log(conn, 'worker', status.value, run_id)
        if stale and result is not None:
            log(conn, 'worker', 'void_evidence', run_id)


def _batch_row(payload, batch_id):
    for row in payload.get('batches') or []:
        if isinstance(row, dict) and row.get('batch_id') == batch_id:
            return row
    return None


def correct(case_id, form, actor):
    """Register a byte-count correction, producing a new snapshot revision.

    Repeating the same ``request_key`` returns the original registration instead of
    stacking another revision. Old reports keep their text but become void, and any
    handover already completed from them is flagged for recovery.
    """
    try:
        return _correct(case_id, form, actor)
    except IntegrityError:
        pass
    with engine.connect() as conn:
        existing = conn.execute(select(corrections).where(
            corrections.c.case_id == case_id, corrections.c.request_key == form.request_key)).mappings().first()
        if existing is None:
            raise HTTPException(409, '更正登记冲突，请重试')
        return _correction_result(conn, dict(existing), duplicate=True)


def _correct(case_id, form, actor):
    with engine.begin() as conn:
        case = conn.execute(select(cases).where(cases.c.id == case_id).with_for_update()).mappings().first()
        if case is None:
            raise HTTPException(404, '找不到该档案')
        existing = conn.execute(select(corrections).where(
            corrections.c.case_id == case_id, corrections.c.request_key == form.request_key)).mappings().first()
        if existing is not None:
            return _correction_result(conn, dict(existing), duplicate=True)

        payload = deepcopy(case['payload'])
        row = _batch_row(payload, form.batch_id)
        if row is None:
            raise HTTPException(422, f'盘点中没有批次 {form.batch_id}')
        old_size = row.get('size_bytes')
        if form.old_size_bytes is not None and form.old_size_bytes != old_size:
            raise HTTPException(409, f'旧字节数与当前盘点不一致，当前为 {old_size}')
        if form.new_size_bytes == old_size:
            raise HTTPException(422, '更正的字节数与当前盘点相同，无需登记')
        row['size_bytes'] = form.new_size_bytes
        try:
            domain.validate(payload)
        except (ValueError, TypeError) as exc:
            raise HTTPException(422, str(exc)) from None

        revision = case_revision(conn, case_id) + 1
        conn.execute(cases.update().where(cases.c.id == case_id).values(payload=payload, revision=revision))
        conn.execute(case_revisions.insert().values(case_id=case_id, revision=revision, payload=payload,
                                                    created_at=utc_time()))
        correction_id = conn.execute(corrections.insert().values(
            case_id=case_id, request_key=form.request_key, batch_id=form.batch_id,
            old_size_bytes=old_size, new_size_bytes=form.new_size_bytes, reason=form.reason,
            actor=actor, revision=revision, created_at=utc_time())).inserted_primary_key[0]
        log(conn, actor, 'correct_case', case_id)

        stale_ids = [row.id for row in conn.execute(
            select(evidence.c.id).select_from(evidence.join(runs, evidence.c.run_id == runs.c.id))
            .where(runs.c.case_id == case_id)).all()]
        if stale_ids:
            conn.execute(evidence.update().where(evidence.c.id.in_(stale_ids), evidence.c.state != EvidenceState.VOID)
                         .values(state=EvidenceState.VOID, voided_at=utc_time(),
                                 void_reason=f'盘点已更正至第 {revision} 版，旧数报告作废'))
            conn.execute(handovers.update().where(handovers.c.evidence_id.in_(stale_ids),
                          handovers.c.status == HandoverStatus.HANDED_OVER)
                         .values(status=HandoverStatus.PENDING_RECOVERY, updated_at=utc_time()))
            log(conn, actor, 'void_evidence', case_id)
        return _correction_result(conn, found(conn, corrections, correction_id), duplicate=False)


def _correction_result(conn, correction, duplicate):
    case = found(conn, cases, correction['case_id'])
    return {'correction': correction, 'case': case, 'duplicate': duplicate}


def corrections_for(case_id):
    with engine.connect() as conn:
        found(conn, cases, case_id)
        return [dict(row) for row in conn.execute(
            select(corrections).where(corrections.c.case_id == case_id)
            .order_by(corrections.c.id)).mappings()]


def recent_corrections():
    with engine.connect() as conn:
        return [dict(row) for row in conn.execute(
            select(corrections.c.id, corrections.c.case_id, cases.c.title, corrections.c.request_key,
                   corrections.c.batch_id, corrections.c.old_size_bytes, corrections.c.new_size_bytes,
                   corrections.c.reason, corrections.c.actor, corrections.c.revision, corrections.c.created_at)
            .select_from(corrections.join(cases, corrections.c.case_id == cases.c.id))
            .order_by(corrections.c.id.desc()).limit(100)).mappings()]


def revisions_for(case_id):
    with engine.connect() as conn:
        found(conn, cases, case_id)
        return [dict(row) for row in conn.execute(
            select(case_revisions.c.revision, case_revisions.c.created_at).where(
                case_revisions.c.case_id == case_id).order_by(case_revisions.c.revision)).mappings()]


def review(identity, note, actor):
    note = note.strip()
    if not note:
        raise HTTPException(422, '复核意见不能为空')
    with engine.begin() as conn:
        row = conn.execute(select(evidence).where(evidence.c.id == identity)).mappings().first()
        if row is None:
            raise HTTPException(404, '找不到该记录')
        run = found(conn, runs, row['run_id'])
        # Lock order case -> evidence matches corrections, so a concurrent correction
        # and signature resolve by whichever transaction takes effect first.
        case = conn.execute(select(cases.c.id).where(cases.c.id == run['case_id']).with_for_update()).first()
        current = conn.execute(select(evidence).where(evidence.c.id == identity).with_for_update()).mappings().first()
        if current['state'] != EvidenceState.VALID:
            raise HTTPException(409, '报告已作废，停止签署')
        if run['revision'] is not None and current['revision'] != case_revision(conn, run['case_id']):
            raise HTTPException(409, '盘点已更正，旧数报告停止签署')
        if current['reviewed_at'] is not None:
            raise HTTPException(409, '该证据已经复核')
        conn.execute(evidence.update().where(evidence.c.id == identity)
                     .values(review_note=note, reviewer=actor, reviewed_at=utc_time()))
        log(conn, actor, 'review', identity)
        return found(conn, evidence, identity)


def handover(identity, note, actor):
    note = (note or '').strip() or None
    with engine.begin() as conn:
        row = conn.execute(select(evidence).where(evidence.c.id == identity)).mappings().first()
        if row is None:
            raise HTTPException(404, '找不到该记录')
        run = found(conn, runs, row['run_id'])
        conn.execute(select(cases.c.id).where(cases.c.id == run['case_id']).with_for_update()).first()
        current = conn.execute(select(evidence).where(evidence.c.id == identity).with_for_update()).mappings().first()
        existing = conn.execute(select(handovers).where(handovers.c.evidence_id == identity)
                                .with_for_update()).mappings().first()
        if existing is not None and existing['status'] == HandoverStatus.HANDED_OVER:
            return dict(existing)
        if current['state'] != EvidenceState.VALID:
            raise HTTPException(409, '报告已作废，停止交接')
        if current['reviewed_at'] is None:
            raise HTTPException(409, '报告尚未复核，不能交接')
        if current['revision'] is not None and current['revision'] != case_revision(conn, run['case_id']):
            raise HTTPException(409, '盘点已更正，须用新数重算并复核后再交接')
        if existing is not None:
            raise HTTPException(409, f'该交接记录状态为 {existing["status"]}，不能重复交接')
        handover_id = conn.execute(handovers.insert().values(
            evidence_id=identity, status=HandoverStatus.HANDED_OVER, actor=actor, note=note,
            created_at=utc_time(), updated_at=utc_time())).inserted_primary_key[0]
        log(conn, actor, 'handover', identity)
        return found(conn, handovers, handover_id)


def recover(identity, note, actor):
    note = (note or '').strip() or None
    with engine.begin() as conn:
        row = conn.execute(select(handovers).where(handovers.c.id == identity).with_for_update()).mappings().first()
        if row is None:
            raise HTTPException(404, '找不到该交接记录')
        if row['status'] == HandoverStatus.RECOVERED:
            return dict(row)
        if row['status'] != HandoverStatus.PENDING_RECOVERY:
            raise HTTPException(409, '该交接记录不在待追回状态')
        conn.execute(handovers.update().where(handovers.c.id == identity).values(
            status=HandoverStatus.RECOVERED, note=note or row['note'], updated_at=utc_time()))
        log(conn, actor, 'recover_handover', identity)
        return found(conn, handovers, identity)


def _effective_status(ev, case_revision, handover_row):
    if handover_row is not None:
        return handover_row['status']
    if ev['state'] != EvidenceState.VALID or ev['reviewed_at'] is None:
        return 'unavailable'
    if ev['revision'] is not None and ev['revision'] != case_revision:
        return 'unavailable'
    return HandoverStatus.AVAILABLE


def list_handovers(status=None):
    with engine.connect() as conn:
        rows = conn.execute(
            select(evidence.c.id, evidence.c.run_id, evidence.c.state, evidence.c.revision,
                   evidence.c.reviewer, evidence.c.reviewed_at, evidence.c.void_reason,
                   evidence.c.report, runs.c.case_id, cases.c.title, cases.c.revision.label('case_revision'),
                   handovers.c.id.label('handover_id'), handovers.c.status.label('handover_status'),
                   handovers.c.actor.label('handover_actor'), handovers.c.created_at.label('handovered_at'),
                   handovers.c.note, handovers.c.updated_at.label('handover_updated_at'))
            .select_from(evidence.join(runs, evidence.c.run_id == runs.c.id)
                         .join(cases, runs.c.case_id == cases.c.id)
                         .outerjoin(handovers, handovers.c.evidence_id == evidence.c.id))
            .order_by(evidence.c.id.desc()).limit(200)).mappings().all()
    result = []
    for row in rows:
        row = dict(row)
        handover_row = {'status': row['handover_status']} if row['handover_id'] else None
        row['handover_status'] = _effective_status(row, row['case_revision'], handover_row)
        row['summary'] = (row.pop('report') or {}).get('summary')
        result.append(row)
    if status:
        result = [row for row in result if row['handover_status'] == status]
    return result
