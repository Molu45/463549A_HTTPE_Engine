from decimal import Decimal
from main import HTTPEngine, TransactionRecord


def test_engine_idempotency_and_settlement():
    """Verifies duplicate transaction suppression and accurate ledger settlement."""
    engine = HTTPEngine()

    txns = [
        TransactionRecord("T-01", "ACC-01", Decimal("500.00"), "CREDIT"),
        TransactionRecord("T-01", "ACC-01", Decimal("500.00"), "CREDIT"),  # Duplicate retry
        TransactionRecord("T-02", "ACC-01", Decimal("200.00"), "DEBIT"),
        TransactionRecord("T-03", "ACC-02", Decimal("1000.00"), "CREDIT"),
    ]

    accepted, deduped, volume = engine.process_batch(txns)

    # Core Invariants Validation
    assert accepted == 3, f"Expected 3 accepted transactions, got {accepted}"
    assert deduped == 1, f"Expected 1 duplicate filtered, got {deduped}"
    assert volume == Decimal("1700.00"), f"Expected 1700.00 total volume, got {volume}"
    assert engine.ledger["ACC-01"] == Decimal("300.00"), "ACC-01 balance mismatch"
    assert engine.ledger["ACC-02"] == Decimal("1000.00"), "ACC-02 balance mismatch"


def test_zero_drift_invariant():
    """Verifies double-entry ledger balance conservation (Credit == Debit)."""
    engine = HTTPEngine()

    txns = [
        TransactionRecord("T-A", "SYS-CLEARING", Decimal("25000.00"), "CREDIT"),
        TransactionRecord("T-B", "SYS-CLEARING", Decimal("25000.00"), "DEBIT"),
    ]

    accepted, deduped, _ = engine.process_batch(txns)
    assert accepted == 2
    assert engine.ledger["SYS-CLEARING"] == Decimal("0.00"), "Clearing balance drift detected"
