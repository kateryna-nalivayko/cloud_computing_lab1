#!/usr/bin/env bash
# Видаляє всі ресурси, створені create_cluster.sh (щоб не витрачати кредити).
# Запускати в Cloud Shell:   bash deploy/delete_cluster.sh
set -uo pipefail

ZONE="${ZONE:-europe-west1-c}"
REGION="${ZONE%-*}"

INSTANCES="$(gcloud compute instances list --filter='name~^parcs-' --format='value(name)')"
if [ -n "$INSTANCES" ]; then
  echo "== Видаляю ВМ: $INSTANCES"
  gcloud compute instances delete $INSTANCES --zone="$ZONE" --quiet
fi

echo "== Видаляю Cloud NAT і роутер..."
gcloud compute routers nats delete parcs-nat --router=parcs-router --region="$REGION" --quiet 2>/dev/null
gcloud compute routers delete parcs-router --region="$REGION" --quiet 2>/dev/null

echo "== Видаляю правила firewall..."
gcloud compute firewall-rules delete parcs-internal parcs-web --quiet 2>/dev/null

echo "Готово. Перевірте, що список порожній:"
gcloud compute instances list
