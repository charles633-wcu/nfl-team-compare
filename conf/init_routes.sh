#!/bin/sh
set -e

echo "Waiting for APISIX Admin API..."
until curl -sS http://apisix:9180/apisix/admin/routes >/dev/null 2>&1; do
  sleep 1
done

echo "Pushing routes..."
# routes.json contains an array; push each route by id
for id in 1 2; do
  body=$(jq -c ".routes[] | select(.id==\"$id\") | del(.id)" /conf/routes.json)
  curl -sS -X PUT "http://apisix:9180/apisix/admin/routes/$id" \
    -H "Content-Type: application/json" \
    -d "$body" >/dev/null
  echo "  loaded route $id"
done

echo "Done."
