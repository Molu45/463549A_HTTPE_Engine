import http from 'k6/http';
import { check, sleep } from 'k6';
import { uuidv4 } from 'https://jslib.k6.io/k6-utils/1.4.0/index.js';

export const options = {
  scenarios: {
    sustained_12k_tps: {
      executor: 'ramping-arrival-rate',
      startRate: 1000,
      timeUnit: '1s',
      preAllocatedVUs: 1500,
      maxVUs: 4000,
      stages: [
        { duration: '2m', target: 5000 },   // Warm-up ramp
        { duration: '3m', target: 12000 },  // Ramp to sustained target
        { duration: '10m', target: 12000 }, // Steady state sustained 12,000 TPS
        { duration: '2m', target: 0 },      // Cool-down
      ],
    },
  },
  thresholds: {
    http_req_duration: ['p(99)<100', 'p(95)<50', 'p(50)<15'], // SLA thresholds
    http_req_failed: ['rate<0.001'],                           // Error rate < 0.1%
  },
};

const BASE_URL = __ENV.API_BASE_URL || 'https://api.payscale.internal/v1';

export default function () {
  const idempotencyKey = uuidv4();
  const payload = JSON.stringify({
    source_account_id: '018f2d5e-7a1b-789a-bcde-0123456789aa',
    destination_account_id: '018f2d5e-7a1b-789a-bcde-0123456789bb',
    amount: 150.00,
    currency: 'INR',
    metadata: { test_run: '12k_sustained_bench' }
  });

  const params = {
    headers: {
      'Content-Type': 'application/json',
      'Idempotency-Key': idempotencyKey,
      'Authorization': 'Bearer test-jwt-token',
    },
  };

  const res = http.post(`${BASE_URL}/payments`, payload, params);

  check(res, {
    'status is 202 or 200': (r) => r.status === 202 || r.status === 200,
    'latency under 100ms': (r) => r.timings.duration < 100,
  });
}