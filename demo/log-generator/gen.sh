#!/bin/sh
# Pushes a mix of normal and failing log lines into Loki for two services.
push() {
  ts="$(date +%s)000000000"
  curl -s -o /dev/null -H 'Content-Type: application/json' \
    -X POST http://loki:3100/loki/api/v1/push \
    --data "{\"streams\":[{\"stream\":{\"job\":\"$1\",\"pod\":\"$2\"},\"values\":[[\"$ts\",\"$3\"]]}]}"
}
until curl -sf http://loki:3100/ready >/dev/null; do sleep 2; done
i=0
while true; do
  i=$((i + 1))
  push checkout checkout-7d9f "level=info msg=\\\"order placed\\\" id=$i latency_ms=$((40 + i % 30))"
  if [ $((i % 4)) -eq 0 ]; then
    push checkout checkout-7d9f "level=error msg=\\\"payment provider timeout\\\" upstream=payments:443 after=5s"
  fi
  push log-shipper shipper-site-07 "level=error msg=\\\"remote write failed\\\" err=\\\"x509: certificate has expired or is not yet valid\\\""
  sleep 5
done
