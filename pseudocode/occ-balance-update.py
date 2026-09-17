"""
PayScale HTTPE - Optimistic Concurrency Control (OCC) Balance Engine
File: pseudocode/occ-balance-update.py
Evaluates: Atomicity, Write-Skew Elimination, Dynamic Jittered Backoff
"""

import time
import random
from typing import Tuple, Dict, Any

class InsufficientFundsException(Exception):
    pass

class MaxRetriesExhaustedException(Exception):
    pass

class AccountFrozenException(Exception):
    pass


def execute_occ_debit(db_pool, account_id: str, debit_amount: float, max_retries: int = 5) -> Dict[str, Any]:
    """
    Executes an atomic debit on an account using Optimistic Concurrency Control (OCC).
    Guarantees no double-spending and zero lock holding across network hops.
    """
    attempt = 0
    base_backoff_ms = 10  # 10ms starting backoff

    while attempt < max_retries:
        # Step 1: Fetch current state with monotonic version counter
        # Isolation: READ COMMITTED snapshot
        account = db_pool.query_one(
            """
            SELECT available_balance, version, status 
            FROM accounts 
            WHERE account_id = :account_id
            """,
            account_id=account_id
        )

        if not account:
            raise ValueError(f"Account {account_id} does not exist.")

        if account["status"] != "ACTIVE":
            raise AccountFrozenException(f"Account {account_id} is in {account['status']} state.")

        current_balance = account["available_balance"]
        current_version = account["version"]

        # Step 2: Validate business invariants in application memory
        if current_balance < debit_amount:
            raise InsufficientFundsException(
                f"Insufficient funds. Required: {debit_amount}, Available: {current_balance}"
            )

        new_balance = current_balance - debit_amount
        new_version = current_version + 1

        # Step 3: Atomic Compare-And-Swap (CAS) write using OCC version validation
        # Checks both version AND balance invariant directly at the database engine level
        rows_affected = db_pool.execute(
            """
            UPDATE accounts 
            SET available_balance = :new_balance,
                version = :new_version,
                updated_at = NOW()
            WHERE account_id = :account_id 
              AND version = :current_version
              AND available_balance >= :debit_amount
            """,
            account_id=account_id,
            new_balance=new_balance,
            new_version=new_version,
            current_version=current_version,
            debit_amount=debit_amount
        )

        # Step 4: Verify write success
        if rows_affected == 1:
            return {
                "success": True,
                "account_id": account_id,
                "previous_balance": current_balance,
                "new_balance": new_balance,
                "version": new_version,
                "retries": attempt
            }

        # Step 5: Version conflict detected (another concurrent transaction updated the account)
        attempt += 1
        if attempt >= max_retries:
            raise MaxRetriesExhaustedException(
                f"Concurrent contention too high on account {account_id}. Retries exhausted."
            )

        # Full jitter backoff: sleep between 0 and min(max_backoff, base * 2^attempt)
        sleep_duration = random.uniform(0, (base_backoff_ms * (2 ** attempt)) / 1000.0)
        time.sleep(sleep_duration)

    raise MaxRetriesExhaustedException("Transaction failed after maximum retries.")