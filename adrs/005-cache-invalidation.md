# ADR-005: Cache Strategy: Cache-Aside with Monotonic Revision Tokens & Explicit Invalidation

## Status
Accepted

## Context
PayScale's architecture requires ultra-low latency reads (<2ms) for account tier validation, balance display checks, and rate-limiting counters under 12,000 TPS. Reading directly from database shards for every request would saturate connection pools. However, in financial systems, serving stale balance data can induce false negative checkouts or conflicting debit requests. The cache strategy must deliver high read performance while eliminating race conditions during concurrent cache refreshes.

## Decision
We select **Cache-Aside (Lazy Loading) combined with Monotonic Version Invalidation and Bounded TTLs** across the 6-node Redis Cluster.

### Protocol Mechanics:
1. **Read Path:** Application queries Redis: `GET account:{account_id}`.
   - *Hit:* If present, immediately deserialize account metadata.
   - *Miss:* Application reads from CockroachDB read-replica, writes back to Redis with a strict 300-second (5 minute) jittered TTL, and attaches the database `version` tag.
2. **Write Path (Invalidate on Commit):** 
   - Balance updates NEVER write-through directly to Redis to avoid phantom states.
   - When a transaction commits in CockroachDB, an eviction signal `DEL account:{account_id}` is executed atomically in Redis via the Transactional Outbox worker.
3. **Idempotency Keys:** Stored as `SET idempotency:{key} {status} EX 86400 NX` (24-hour absolute TTL, no eviction).

## Alternatives Considered

### 1. Write-Through Caching
- *Pros:* Cache is always fresh immediately after write.
- *Cons:* Write path latency increases (synchronous database write + Redis write); dual-failure modes if Redis write drops after DB commit.

### 2. Write-Behind (Write-Back) Caching
- *Pros:* Extremely fast writes (<1ms) since DB is updated asynchronously.
- *Cons:* Strictly unacceptable for financial ledger systems. A crash of the Redis cluster prior to DB flush causes unrecoverable monetary data loss (violating $RPO=0$ and ACID durability).

## Consequences
### Positive Outcomes:
- Zero financial loss risk: CockroachDB remains the single durable source of truth.
- Cache stampedes are mitigated via probabilistic early expiration (XFetch algorithm) and mutex leases on cache misses.

### Negative / Trade-Offs:
- Brief window of cache-miss latency (3-5ms) immediately following an eviction.

## Compliance
- **RBI Financial Integrity:** Guarantees that in-flight ledger mutations never rely on uncommitted, volatile RAM cache states.