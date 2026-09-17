import http from 'k6/http';
import { check } from 'k6';
import { uuidv4 } from 'https://jslib.k6.io/k6-utils/1.4.0/index.js';

export const options = {
  scenarios: {
    flash_sale_spike: {
      executor: 'ramping-arrival-rate',
      startRate: 2000,
      timeUnit: '1s',
      preAllocatedVUs: 2500,
      maxVUs: 6000,
      stages: [
        { duration: '1m', target: 5000 },
        { duration: '30s', target: 18000 }, // Peak Diwali flash sale spike (18,000 TPS)
        { duration: '2m', target: 18000 },  // Sustained burst window
        { duration: '30s', target: 8000 },  // Traffic settling
        { duration: '1m', target: 0 },
      ],
    },
  },
  thresholds: {
    http_req_duration: ['p(99)<150'], // Burst p99 budget allowance < 150ms
    http_req_failed: ['rate<0.01'],   // Error rate under 1% during peak burst
  },
};

const BASE_URL = __ENV.API_BASE_URL || 'https://api.payscale.internal/v1';

export default function () {
  const idempotencyKey = uuidv4();
  const payload = JSON.stringify({
    source_account_id: '018f2d5e-7a1b-789a-bcde-0123456789aa',
    destination_account_id: '018f2d5e-7a1b-789a-bcde-0123456789bb',
    amount: 99.00,
    currency: 'INR',
    metadata: { burst_test: true }
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
    'accepted or queued': (r) => r.status === 202 || r.status === 200 || r.status === 429,
  });
}