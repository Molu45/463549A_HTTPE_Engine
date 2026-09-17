"""
PayScale HTTPE - Distributed Saga Orchestration Engine
File: pseudocode/saga-orchestrator.py
Evaluates: Distributed Transactions across Database Shards with Compensating Actions
"""

import uuid
import json
from typing import Dict, Any

class SagaStepStatus:
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    COMPENSATED = "COMPENSATED"

class SagaOrchestrator:
    def __init__(self, db_client, kafka_producer, audit_service):
        self.db = db_client
        self.kafka = kafka_producer
        self.audit = audit_service

    def process_p2p_payment(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Executes a 2-Shard P2P Payment Workflow:
        Step 1: Debit Source Account (Shard A)
        Step 2: Credit Destination Account (Shard B)
        Compensate Step 1 if Step 2 fails (Rollback within 30s SLA)
        """
        saga_id = str(uuid.uuid4())
        txn_id = payload["transaction_id"]
        source_id = payload["source_account_id"]
        dest_id = payload["destination_account_id"]
        amount = payload["amount"]

        self._log_saga_event(saga_id, txn_id, "INITIATED", "PROCESSING", payload)

        # --- STEP 1: DEBIT SENDER ON SHARD A ---
        debit_result = self._execute_sub_transaction(
            account_id=source_id,
            action="DEBIT",
            amount=amount,
            saga_id=saga_id
        )

        if not debit_result["success"]:
            self._log_saga_event(saga_id, txn_id, "PROCESSING", "FAILED", {"reason": debit_result["error"]})
            self._update_transaction_status(txn_id, "FAILED", debit_result["error"])
            return {"status": "FAILED", "reason": debit_result["error"], "saga_id": saga_id}

        self._log_saga_event(saga_id, txn_id, "DEBIT_COMMITTED", "CREDITING", {"source": source_id})

        # --- STEP 2: CREDIT RECEIVER ON SHARD B ---
        credit_result = self._execute_sub_transaction(
            account_id=dest_id,
            action="CREDIT",
            amount=amount,
            saga_id=saga_id
        )

        if not credit_result["success"]:
            # Destination credit failed -> Trigger Step 1 Compensating Action (Auto-Refund)
            self._log_saga_event(saga_id, txn_id, "CREDIT_FAILED", "COMPENSATING", {"reason": credit_result["error"]})
            
            compensation = self._execute_sub_transaction(
                account_id=source_id,
                action="CREDIT",
                amount=amount,
                saga_id=saga_id,
                is_compensation=True
            )

            if compensation["success"]:
                self._log_saga_event(saga_id, txn_id, "COMPENSATING", "REVERSED", {"refunded": True})
                self._update_transaction_status(txn_id, "REVERSED", f"Credit failed: {credit_result['error']}")
                return {"status": "REVERSED", "reason": credit_result["error"], "saga_id": saga_id}
            else:
                # Critical compensation failure -> Route immediately to DLQ for manual intervention
                self._log_saga_event(saga_id, txn_id, "COMPENSATION_CRITICAL_FAILURE", "DLQ", {})
                self.kafka.publish("txn.dead.letter.queue", {"saga_id": saga_id, "txn_id": txn_id, "payload": payload})
                return {"status": "FATAL_ERROR", "reason": "Compensation failed, routed to DLQ"}

        # --- STEP 3: EMIT DOUBLE-ENTRY LEDGER & AUDIT TRAIL ---
        self._record_double_entry_ledger(txn_id, source_id, dest_id, amount)
        self._update_transaction_status(txn_id, "COMPLETED")
        self._log_saga_event(saga_id, txn_id, "CREDITING", "COMPLETED", {})

        # Publish completion event for notification and analytics workers
        self.kafka.publish("txn.payment.completed", {"transaction_id": txn_id, "saga_id": saga_id})

        return {"status": "COMPLETED", "transaction_id": txn_id, "saga_id": saga_id}

    def _execute_sub_transaction(self, account_id: str, action: str, amount: float, saga_id: str, is_compensation: bool = False):
        # Dispatches query to appropriate CockroachDB range leaseholder
        return self.db.execute_ledger_mutation(account_id, action, amount, saga_id, is_compensation)

    def _log_saga_event(self, saga_id, txn_id, from_state, to_state, payload):
        self.db.execute(
            """
            INSERT INTO transaction_events (event_id, transaction_id, saga_id, from_state, to_state, payload, created_at)
            VALUES (gen_random_uuid(), :txn_id, :saga_id, :from_s, :to_s, :data, NOW())
            """,
            txn_id=txn_id, saga_id=saga_id, from_s=from_state, to_s=to_state, data=json.dumps(payload)
        )

    def _update_transaction_status(self, txn_id, status, failure_reason=None):
        self.db.execute(
            """
            UPDATE transactions 
            SET status = :status, failure_reason = :reason, completed_at = NOW() 
            WHERE transaction_id = :txn_id
            """,
            txn_id=txn_id, status=status, reason=failure_reason
        )

    def _record_double_entry_ledger(self, txn_id, source_id, dest_id, amount):
        # Guarantees debit + credit = 0 balance conservation
        self.db.execute_batch([
            {"table": "ledger_entries", "account_id": source_id, "type": "DEBIT", "amount": amount, "txn_id": txn_id},
            {"table": "ledger_entries", "account_id": dest_id, "type": "CREDIT", "amount": amount, "txn_id": txn_id}
        ])