from decimal import Decimal
from main import HTTPEngine, TransactionRecord


def test_engine_idempotency_and_settlement():
    engine = HTTPEngine()

    txns = [
        TransactionRecord("T-01", "ACC-01", Decimal("500.00"), "CREDIT"),
        TransactionRecord("T-01", "ACC-01", Decimal("500.00"), "CREDIT"),  # Duplicate
        TransactionRecord("T-02", "ACC-01", Decimal("200.00"), "DEBIT"),
        TransactionRecord("T-03", "ACC-02", Decimal("1000.00"), "CREDIT"),
    ]

    accepted, deduped, volume = engine.process_batch(txns)

    # Invariants
    assert accepted == 3
    assert deduped == 1
    assert volume == Decimal("1700.00")
    assert engine.ledger["ACC-01"] == Decimal("300.00")
    assert engine.ledger["ACC-02"] == Decimal("1000.00")


def test_zero_drift_invariant():
    engine = HTTPEngine()

    txns = [
        TransactionRecord("T-A", "SYS-RECON", Decimal("10000.00"), "CREDIT"),
        TransactionRecord("T-B", "SYS-RECON", Decimal("10000.00"), "DEBIT"),
    ]

    accepted, deduped, _ = engine.process_batch(txns)
    assert accepted == 2
    assert engine.ledger["SYS-RECON"] == Decimal("0.00")