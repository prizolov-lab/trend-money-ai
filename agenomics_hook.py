"""Необязательная запись доказательств в Agenomics (по умолчанию выключена).

Включается переменными AGENOMICS_EVIDENCE=1 и (необязательно) AGENOMICS_EVIDENCE_DB.
Нужен пакет agenomics (см. requirements-agenomics.txt). Без них модуль ничего не
делает; любая ошибка логируется и не мешает боту.

Что записывается:
1. Перед генерацией идей: замороженные цели runtime_failure и task_failure.
2. После: runtime_failure (Q1): сбой OpenAI или ответа.
3. Когда пользователь жмёт 👍/👎: task_failure (Q4, независимая группа
   human_review). Текст запросов и ответов в базу НЕ пишется, только факт исхода
   и обезличенный номер задачи.
"""

import logging
import os
import threading
from collections import OrderedDict
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

try:
    from agenomics import (
        AgentGenome,
        EvidenceStore,
        ExternalVerification,
        TrustScorer,
        record_external_outcome,
    )
except ImportError:
    AgentGenome = EvidenceStore = ExternalVerification = TrustScorer = None
    record_external_outcome = None

AGENT_ID = "trend-money-ai"
ENVIRONMENT_ID = "trend-money-ai/telegram-bot"
SOURCE = "trend-money-ai/bot"
MAX_PENDING = 500

RUNTIME_DONOR = dict(
    donor_id="tma.runtime", donor_type="outcome", name="Бот: сбои OpenAI и ответа",
    independence_group="runtime", provider="trend-money-ai",
)
HUMAN_DONOR = dict(
    donor_id="tma.human_review", donor_type="outcome", name="Оценка идей пользователем",
    independence_group="human_review", provider="users",
)


def enabled() -> bool:
    return os.environ.get("AGENOMICS_EVIDENCE", "") == "1" and EvidenceStore is not None


def _db_path() -> str:
    return os.environ.get("AGENOMICS_EVIDENCE_DB") or "agenomics_evidence.db"


class _Verifier:
    donor_id = HUMAN_DONOR["donor_id"]

    def __init__(self, positive, reference, verified_at):
        self.positive, self.reference, self.verified_at = positive, reference, verified_at

    def verify(self, prediction):
        return ExternalVerification(
            occurred=not self.positive,
            outcome_type="task_failure",
            source_type="human_review",
            source_reference=self.reference,
            verification_method="manual_review",
            verified_at=self.verified_at,
        )


class Hook:
    def __init__(self, db_path=None):
        self._db = db_path or _db_path()
        self._lock = threading.Lock()
        self._n = 0
        self._failed = []  # исходы runtime прошлых задач (True = сбой)
        self._pending = OrderedDict()  # task_no -> id предсказания task_failure

    def _trust(self):
        recent = self._failed[-200:]
        drift = round(sum(recent) / len(recent), 4) if len(recent) >= 10 else 0.05
        genome = AgentGenome(
            id=AGENT_ID, domain="business", autonomy="advisory", transparency=60.0,
            bias_control=50.0, data_safety=70.0, drift_rate=drift, has_ledger=False,
        )
        return TrustScorer().score(genome)

    def start(self):
        """Перед задачей. Возвращает (номер задачи, id runtime-цели) или None."""
        try:
            with self._lock:
                self._n += 1
                now = datetime.now(timezone.utc)
                store = EvidenceStore(self._db)
                try:
                    trust = self._trust()
                    obs = store.record_observation(
                        AGENT_ID, trust.score, trust.label, genome_hash="tma-v1",
                        model_version="gpt-4o-mini", source=SOURCE, timestamp=now,
                    )
                    ids = {
                        t: store.record_prediction(
                            obs, t, horizon="current_run", frozen_at=now,
                            task_version=f"tma:{self._n}", environment_id=ENVIRONMENT_ID,
                        )
                        for t in ("runtime_failure", "task_failure")
                    }
                finally:
                    store.close()
                self._pending[self._n] = ids["task_failure"]
                while len(self._pending) > MAX_PENDING:
                    self._pending.popitem(last=False)
                return self._n, ids["runtime_failure"]
        except Exception:
            logger.exception("Agenomics: заморозка не удалась; бот продолжает")
            return None

    def finish(self, token, failed: bool):
        if token is None:
            return
        try:
            with self._lock:
                store = EvidenceStore(self._db)
                try:
                    store.register_donor(**RUNTIME_DONOR)
                    store.record_outcome(
                        token[1], RUNTIME_DONOR["donor_id"], "execution_error",
                        occurred=failed, outcome_class="RUNTIME", quality_level="Q1",
                        source_reference=f"tma-task:{token[0]}",
                        details=f"failed={failed}",
                    )
                finally:
                    store.close()
                self._failed.append(failed)
        except Exception:
            logger.exception("Agenomics: исход не записан")

    def human(self, task_no: int, positive: bool):
        """Оценка пользователя (Q4). Повторное нажатие игнорируется."""
        try:
            with self._lock:
                pred = self._pending.pop(task_no, None)
                if pred is None:
                    return
                store = EvidenceStore(self._db)
                try:
                    store.register_donor(**HUMAN_DONOR)
                    record_external_outcome(
                        store, pred,
                        _Verifier(positive, f"tma-task:{task_no}:human",
                                  datetime.now(timezone.utc)),
                    )
                finally:
                    store.close()
        except Exception:
            logger.exception("Agenomics: оценка не записана")


HOOK = Hook() if enabled() else None
