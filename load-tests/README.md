# Load Tests

Load testing scripts for SafeRoute API using k6.

## Prerequisites

Install k6: https://k6.io/docs/getting-started/installation/

## Run tests

```bash
# Basic health check load test
k6 run load-tests/saferoute-load-test.js

# Against production
BASE_URL=https://saferoute-api.vercel.app k6 run load-tests/saferoute-load-test.js

# With more virtual users
k6 run -u 200 -d 2m load-tests/saferoute-load-test.js
```
