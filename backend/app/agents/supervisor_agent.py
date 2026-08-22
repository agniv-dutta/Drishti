"""SupervisorAgent - orchestrates analyzer -> strategist -> executor.

Owns the full lifecycle: payment ingestion (with dedupe), analysis (cached),
candidate detection, plan construction, execution, drift monitoring - and
guarantees every stage is auditable in both the JSONL trail and the DB.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.analyzer_agent import AnalyzerAgent
from app.agents.base_agent import BaseAgent
from app.agents.executor_agent import ExecutorAgent
from app.agents.strategist_agent import StrategistAgent
from app.cache.redis_client import get_cache
from app.core.config import get_settings
from app.core.logging_config import get_logger
from app.database.models import PaymentRecord, RecoveryRecord, new_id
from app.ml.data_preprocessor import FEATURE_NAMES, build_features
from app.ml.drift_detector import DriftDetector
from app.ml.recovery_classifier import get_recovery_classifier
from app.models.audit import AuditEventType, AuditSeverity
from app.models.payment import (
    CustomerInfo,
    FailureReason,
    PaymentStatus,
    PaymentTransaction,
    utcnow,
)
from app.models.recovery import ExecutionResult, FailureAnalysis, RecoveryPlan, RecoveryStatus, RecoveryStrategy
from app.schemas.payment_schemas import PaymentIngestRequest
from app.schemas.recovery_schemas import DetectRequest, DetectResponse, DetectedCandidate
from app.utils.encryption import encrypt_dict
from app.utils.formatters import paise_to_rupees, rupees_to_paise

logger = get_logger("drishti.agent.supervisor")

ACTIVE_RECOVERY_STATUSES = [
    RecoveryStatus.PENDING.value,
    RecoveryStatus.PLANNED.value,
    RecoveryStatus.IN_PROGRESS.value,
    RecoveryStatus.SUCCEEDED.value,
]

DRIFT_REFERENCE_KEY = "drift:reference"
DRIFT_CURRENT_KEY = "drift:current"
DRIFT_CHECK_EVERY = 50  # analyses between drift checks


class SupervisorError(Exception):
    """Domain error safe to surface to API callers."""


class PaymentNotFoundError(SupervisorError):
    pass


class RecoveryNotFoundError(SupervisorError):
    pass


class SupervisorAgent(BaseAgent):
    name = "supervisor"
    description = "End-to-end recovery orchestration with full audit coverage"

    def __init__(self) -> None:
        super().__init__()
        self.analyzer = AnalyzerAgent()
        self.strategist = StrategistAgent()
        self.executor = ExecutorAgent()

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _bind_all(self, db: Session) -> None:
        for agent in (self.analyzer, self.strategist, self.executor):
            agent.bind_db(db)
        self.bind_db(db)

    def _get_payment(self, db: Session, payment_id: str) -> PaymentRecord:
        record = db.get(PaymentRecord, payment_id)
        if record is None:
            raise PaymentNotFoundError(f"payment '{payment_id}' not found")
        return record

    @staticmethod
    def _priority(amount_inr: float, risk_score: float) -> str:
        settings = get_settings()
        high_value = amount_inr >= settings.high_value_threshold_inr
        if high_value and risk_score >= 0.65:
            return "P0"
        if risk_score >= 0.65 or high_value:
            return "P1"
        if risk_score >= 0.45:
            return "P2"
        return "P3"

    # ------------------------------------------------------------------
    # ingest
    # ------------------------------------------------------------------
    async def ingest_payment(
        self, db: Session, payload: PaymentIngestRequest
    ) -> Tuple[PaymentRecord, bool]:
        self._bind_all(db)
        existing = (
            db.query(PaymentRecord)
            .filter(
                PaymentRecord.order_id == payload.order_id,
                PaymentRecord.attempt_number == payload.attempt_number,
            )
            .first()
        )
        if existing is not None:
            logger.info("payment.duplicate_ignored", order_id=payload.order_id, payment_id=existing.id)
            return existing, True

        txn = PaymentTransaction(
            payment_id=new_id(),
            order_id=payload.order_id,
            gateway_payment_id=payload.gateway_payment_id,
            customer=CustomerInfo(
                name=payload.customer.name,
                email=str(payload.customer.email),
                phone=payload.customer.phone,
            ),
            amount_paise=payload.amount_paise,
            currency=payload.currency,
            method=payload.method,
            status=payload.status,
            error_code=payload.failure_reason_code,
            error_description=payload.error_description,
            attempt_number=payload.attempt_number,
            meta=dict(payload.metadata),
        )

        from app.utils.formatters import mask_email

        contact_encrypted = encrypt_dict({"email": txn.customer.email, "phone": txn.customer.phone})
        record = PaymentRecord.from_domain(txn, contact_encrypted)
        record.customer_email_masked = mask_email(txn.customer.email)
        db.add(record)
        db.flush()

        self.audit(
            AuditEventType.PAYMENT_INGESTED,
            resource_type="payment",
            resource_id=record.id,
            outcome=record.status,
            message="payment ingested",
            details={
                "order_id": record.order_id,
                "amount_inr": paise_to_rupees(record.amount_paise),
                "method": record.method,
                "gateway_code": record.error_code,
            },
        )
        return record, False

    # ------------------------------------------------------------------
    # analyze
    # ------------------------------------------------------------------
    async def analyze_payment(
        self, db: Session, payment_id: str, force: bool = False
    ) -> Tuple[PaymentRecord, FailureAnalysis]:
        self._bind_all(db)
        record = self._get_payment(db, payment_id)

        cache = await get_cache()
        cache_key = f"analysis:{payment_id}"
        if not force:
            cached = await cache.get_json(cache_key)
            if cached:
                analysis = FailureAnalysis(**cached)
                return record, analysis

        txn = record.to_domain()
        analysis = await self.analyzer.run(txn)

        if not force:
            await cache.set_json(cache_key, analysis.model_dump(mode="json"))

        record.risk_score = analysis.risk_score
        record.risk_band = analysis.risk_band
        db.add(record)
        db.flush()

        await self._sample_drift(txn)
        return record, analysis

    # ------------------------------------------------------------------
    # detect candidates
    # ------------------------------------------------------------------
    async def detect_candidates(self, db: Session, req: DetectRequest) -> DetectResponse:
        self._bind_all(db)
        settings = get_settings()
        cutoff = utcnow() - timedelta(hours=req.lookback_hours)

        query = (
            db.query(PaymentRecord)
            .filter(
                PaymentRecord.status == PaymentStatus.FAILED.value,
                PaymentRecord.created_at >= cutoff,
                PaymentRecord.amount_paise >= rupees_to_paise(req.min_amount_inr),
                PaymentRecord.amount_paise <= rupees_to_paise(req.max_amount_inr),
            )
            .order_by(PaymentRecord.created_at.desc())
        )
        if req.payment_ids:
            query = query.filter(PaymentRecord.id.in_(req.payment_ids))

        active_recovery_subq = select(RecoveryRecord.payment_id).where(
            RecoveryRecord.status.in_(ACTIVE_RECOVERY_STATUSES)
        )
        query = query.filter(~PaymentRecord.id.in_(active_recovery_subq))

        scanned = 0
        persisted = 0
        candidates: List[DetectedCandidate] = []

        for record in query.yield_per(25):
            if len(candidates) >= req.limit:
                break
            scanned += 1
            try:
                _, analysis = await self.analyze_payment(db, record.id)
            except Exception as exc:  # noqa: BLE001 - skip broken rows, keep scanning
                logger.warning("detect.analyze_failed", payment_id=record.id, error=str(exc))
                continue
            if analysis.retryability.value == "not_retryable" or analysis.risk_score < req.min_risk_score:
                continue

            amount_inr = paise_to_rupees(record.amount_paise)
            strategy = get_recovery_classifier().choose_strategy(
                retryability=analysis.retryability,
                risk_score=analysis.risk_score,
                amount_inr=amount_inr,
                high_value_threshold_inr=settings.high_value_threshold_inr,
            )
            priority = self._priority(amount_inr, analysis.risk_score)
            candidates.append(
                DetectedCandidate(
                    payment_id=record.id,
                    amount_inr=amount_inr,
                    failure_reason=FailureReason(record.failure_reason or "unknown"),
                    risk_score=analysis.risk_score,
                    risk_band=analysis.risk_band,
                    retryability=analysis.retryability.value,
                    recommended_strategy=strategy,
                    priority=priority,
                    expected_recovery_inr=round(amount_inr * analysis.risk_score, 2),
                )
            )

            if req.persist_candidates:
                rec = RecoveryRecord(
                    id=new_id(),
                    payment_id=record.id,
                    strategy=strategy.value,
                    status=RecoveryStatus.PENDING.value,
                    priority=priority,
                    risk_score=analysis.risk_score,
                    expected_amount_paise=record.amount_paise,
                    max_attempts=settings.max_recovery_attempts,
                    analysis_json=analysis.model_dump(mode="json"),
                )
                db.add(rec)
                db.flush()
                persisted += 1

        # Highest expected value first.
        candidates.sort(key=lambda c: c.expected_recovery_inr, reverse=True)
        return DetectResponse(
            scanned_count=scanned,
            candidate_count=len(candidates),
            persisted_count=persisted,
            candidates=candidates,
            detected_at=utcnow(),
        )

    # ------------------------------------------------------------------
    # plan
    # ------------------------------------------------------------------
    async def build_plan(
        self,
        db: Session,
        payment_id: str,
        override_strategy: Optional[RecoveryStrategy] = None,
        persist: bool = True,
    ) -> Tuple[RecoveryPlan, Optional[RecoveryRecord]]:
        self._bind_all(db)
        record = self._get_payment(db, payment_id)
        txn = record.to_domain()
        analysis = await self.analyzer.run(txn)

        record.risk_score = analysis.risk_score
        record.risk_band = analysis.risk_band
        db.add(record)
        db.flush()

        plan = await self.strategist.run(txn, analysis, override_strategy)

        recovery_record: Optional[RecoveryRecord] = None
        if persist:
            recovery_record = self._open_recovery_record(db, record)
            recovery_record.analysis_json = analysis.model_dump(mode="json")
            recovery_record.save_plan(plan)
            recovery_record.priority = self._priority(txn.amount_inr, analysis.risk_score)
            recovery_record.risk_score = analysis.risk_score
            db.add(recovery_record)
            db.flush()

        cache = await get_cache()
        await cache.set_json(f"plan:{plan.plan_id}", plan.model_dump(mode="json"))
        return plan, recovery_record

    def _open_recovery_record(self, db: Session, payment: PaymentRecord) -> RecoveryRecord:
        existing = (
            db.query(RecoveryRecord)
            .filter(
                RecoveryRecord.payment_id == payment.id,
                RecoveryRecord.status == RecoveryStatus.PENDING.value,
            )
            .first()
        )
        if existing is not None:
            return existing
        return RecoveryRecord(
            id=new_id(),
            payment_id=payment.id,
            strategy="pending",
            status=RecoveryStatus.PENDING.value,
            expected_amount_paise=payment.amount_paise,
            max_attempts=get_settings().max_recovery_attempts,
        )

    # ------------------------------------------------------------------
    # execute
    # ------------------------------------------------------------------
    async def execute_recovery(
        self,
        db: Session,
        plan_id: Optional[str] = None,
        payment_id: Optional[str] = None,
        dry_run: bool = False,
    ) -> Tuple[ExecutionResult, RecoveryRecord]:
        self._bind_all(db)

        recovery: Optional[RecoveryRecord] = None
        if plan_id:
            recovery = db.query(RecoveryRecord).filter(RecoveryRecord.id == plan_id).first()
            if recovery is None:
                raise RecoveryNotFoundError(f"recovery '{plan_id}' not found")
        elif payment_id:
            recovery = (
                db.query(RecoveryRecord)
                .filter(RecoveryRecord.payment_id == payment_id)
                .order_by(RecoveryRecord.created_at.desc())
                .first()
            )
            if recovery is None:
                _, recovery = await self.build_plan(db, payment_id)  # auto-plan
            elif recovery.plan_json is None:
                _, recovery = await self.build_plan(db, payment_id)
        else:
            raise SupervisorError("provide either plan_id or payment_id")

        if recovery.status == RecoveryStatus.EXHAUSTED.value:
            raise SupervisorError("recovery attempts exhausted for this payment")

        plan = RecoveryPlan(**recovery.plan_json)
        payment = self._get_payment(db, recovery.payment_id)
        txn = payment.to_domain()

        result = await self.executor.run(plan, txn, dry_run=dry_run)

        if dry_run:
            # No side effects persisted; the plan stays open for a real run.
            recovery.status = RecoveryStatus.PLANNED.value
        else:
            recovery.apply_result(result)
        db.add(recovery)
        db.flush()

        severity = AuditSeverity.INFO if result.success else AuditSeverity.WARNING
        event = AuditEventType.RECOVERY_SUCCEEDED if result.success else AuditEventType.RECOVERY_FAILED
        self.audit(
            event,
            resource_type="recovery",
            resource_id=recovery.id,
            outcome=result.summary[:120],
            severity=severity,
            message=f"cost={result.total_cost_paise}p recovered={result.recovered_amount_paise}p",
            details={"payment_id": recovery.payment_id, "dry_run": dry_run},
        )
        return result, recovery

    # ------------------------------------------------------------------
    # one-shot pipeline (demo / e2e)
    # ------------------------------------------------------------------
    async def run(self, db: Session, payload: PaymentIngestRequest, dry_run: bool = False) -> dict:
        """Full pipeline for one payment: ingest -> analyze -> plan -> execute."""
        return await self.run_full_pipeline(db, payload, dry_run=dry_run)

    async def run_full_pipeline(
        self, db: Session, payload: PaymentIngestRequest, dry_run: bool = False
    ) -> dict:
        record, duplicate = await self.ingest_payment(db, payload)
        _, analysis = await self.analyze_payment(db, record.id)
        plan, recovery = await self.build_plan(db, record.id)
        if not dry_run:
            result, recovery = await self.execute_recovery(db, plan_id=recovery.id if recovery else None)
        else:
            result = None
        return {
            "payment_id": record.id,
            "duplicate_ingest": duplicate,
            "analysis": analysis.model_dump(mode="json"),
            "plan": plan.model_dump(mode="json"),
            "recovery_id": recovery.id if recovery else None,
            "execution": result.model_dump(mode="json") if result else "dry-run",
        }

    # ------------------------------------------------------------------
    # drift monitoring
    # ------------------------------------------------------------------
    async def _sample_drift(self, txn: PaymentTransaction) -> Optional[dict]:
        features = build_features(txn)
        cache = await get_cache()

        current = await cache.get_json(DRIFT_CURRENT_KEY) or {}
        reference = await cache.get_json(DRIFT_REFERENCE_KEY) or {}

        for name in FEATURE_NAMES:
            current.setdefault(name, []).append(float(features[name]))
            current[name] = current[name][-200:]

        total_samples = min((len(v) for v in current.values()), default=0)
        report = None
        if reference and total_samples >= DRIFT_CHECK_EVERY:
            self._drift.update_reference(reference)
            report = self._drift.check(current)
            if report["drifted"]:
                self.audit(
                    AuditEventType.DRIFT_ALERT,
                    resource_type="ml_model",
                    resource_id="risk-scorer",
                    outcome="drift_detected",
                    severity=AuditSeverity.WARNING,
                    message=f"PSI threshold exceeded for: {', '.join(report['drifted_features'])}",
                    details=report,
                )
            # rotate windows
            reference = {k: list(v) for k, v in current.items()}
            current = {}

        await cache.set_json(DRIFT_CURRENT_KEY, current)
        await cache.set_json(DRIFT_REFERENCE_KEY, reference)
        return report


_supervisor: Optional[SupervisorAgent] = None


def get_supervisor() -> SupervisorAgent:
    global _supervisor
    if _supervisor is None:
        _supervisor = SupervisorAgent()
    return _supervisor
