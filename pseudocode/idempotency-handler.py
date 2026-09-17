"""
PayScale HTTPE - Distributed Idempotency Handler
File: pseudocode/idempotency-handler.py
Evaluates: Exactly-once submission, replay attack defense, 24h key lifecycle
"""

import json
from typing import Dict, Any, Optional

class IdempotencyHandler:
    def __init__(self, redis_cluster, db_pool, ttl_seconds: int = 86400):
        self.redis = redis_cluster
        self.db = db_pool
        self.ttl = ttl_seconds

    def handle_transaction_request(self, idempotency_key: str, payload: Dict[str, Any], process_fn) -> Dict[str, Any]:
        """
        Enforces exactly-once execution for client payment submissions.
        Returns cached response on repeated submissions without duplicate debits.
        """
        cache_key = f"idempotency:{idempotency_key}"

        # Atomic check-and-set in Redis (NX = Only set if not already exists)
        # Sets status as 'IN_FLIGHT' with 24-hour expiration (86400 seconds)
        acquired = self.redis.set(cache_key, json.dumps({"status": "IN_FLIGHT"}), nx=True, ex=self.ttl)

        if not acquired:
            # Duplicate request detected: fetch existing state
            cached_data = self.redis.get(cache_key)
            if cached_data:
                cached_obj = json.loads(cached_data)
                if cached_obj["status"] == "IN_FLIGHT":
                    return {
                        "status": 409,
                        "error": "CONFLICT",
                        "message": "Transaction currently processing. Please do not retry concurrently."
                    }
                elif cached_obj["status"] == "COMPLETED":
                    return {
                        "status": 200,
                        "cached": True,
                        "data": cached_obj["response"]
                    }

            # If evicted from Redis, fallback to CockroachDB durable query
            db_record = self.db.query_one(
                "SELECT transaction_id, status, amount, created_at FROM transactions WHERE idempotency_key = :k",
                k=idempotency_key
            )
            if db_record:
                return {
                    "status": 200,
                    "cached": True,
                    "data": db_record
                }

        # First-time submission: execute business transaction
        try:
            response = process_fn(payload)

            # Update cache to COMPLETED with actual response payload
            self.redis.set(
                cache_key,
                json.dumps({"status": "COMPLETED", "response": response}),
                ex=self.ttl
            )
            return {"status": 200, "cached": False, "data": response}

        except Exception as err:
            # Release or mark as failed so valid clients can retry safely
            self.redis.delete(cache_key)
            raise err