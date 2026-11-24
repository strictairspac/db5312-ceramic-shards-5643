from fastapi import APIRouter, Depends, Query
from sqlalchemy import text

from src.config.settings import cache, engine
from src.controllers.workflow import download
from src.models.tables import audit, cases, evidence, handovers, runs
from src.schemas.workflow import (CaseForm, CorrectionForm, HandoverForm,
                                  LoginForm, RecoveryForm, ReviewForm)
from src.services import domain, workflow
from src.services.security import current_user, login, operator, reviewer

router = APIRouter()


@router.get('/health')
def health():
    with engine.connect() as conn:
        conn.execute(text('SELECT 1')).scalar_one()
    cache.ping()
    return {'ok': True}


@router.post('/login')
def sign_in(form: LoginForm):
    return login(form.username, form.password)


@router.get('/spec')
def spec(_=Depends(current_user)):
    return domain.SPEC


@router.get('/cases')
def list_cases(_=Depends(current_user)):
    return workflow.recent(cases)


@router.post('/cases', status_code=201)
def create_case(form: CaseForm, actor=Depends(operator)):
    return workflow.make_case(form.title, form.payload, actor)


@router.get('/corrections')
def list_all_corrections(_=Depends(current_user)):
    return workflow.recent_corrections()


@router.get('/cases/{case_id}/corrections')
def list_corrections(case_id: int, _=Depends(current_user)):
    return workflow.corrections_for(case_id)


@router.get('/cases/{case_id}/revisions')
def list_revisions(case_id: int, _=Depends(current_user)):
    return workflow.revisions_for(case_id)


@router.post('/cases/{case_id}/corrections', status_code=201)
def create_correction(case_id: int, form: CorrectionForm, actor=Depends(operator)):
    return workflow.correct(case_id, form, actor)


@router.get('/runs')
def list_runs(_=Depends(current_user)):
    return workflow.recent(runs)


@router.post('/cases/{case_id}/runs', status_code=202)
def start_run(case_id: int, actor=Depends(operator)):
    return workflow.enqueue(case_id, actor)


@router.get('/evidence')
def list_evidence(_=Depends(current_user)):
    return workflow.recent(evidence)


@router.get('/evidence/{identity}/download')
def export_evidence(identity: int, _=Depends(current_user)):
    return download(identity)


@router.post('/evidence/{identity}/review')
def review_evidence(identity: int, form: ReviewForm, actor=Depends(reviewer)):
    return workflow.review(identity, form.note, actor)


@router.get('/handovers')
def list_handovers(status: str | None = Query(default=None), _=Depends(current_user)):
    return workflow.list_handovers(status)


@router.post('/evidence/{identity}/handover', status_code=201)
def complete_handover(identity: int, form: HandoverForm, actor=Depends(operator)):
    return workflow.handover(identity, form.note, actor)


@router.post('/handovers/{identity}/recover')
def recover_handover(identity: int, form: RecoveryForm, actor=Depends(operator)):
    return workflow.recover(identity, form.note, actor)


@router.get('/audit')
def list_audit(_=Depends(current_user)):
    return workflow.recent(audit)
