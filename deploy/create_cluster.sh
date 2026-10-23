#!/usr/bin/env bash
# Розгортання кластера PARCS-Python у Google Cloud (Compute Engine).
# Запускати в Cloud Shell:   bash deploy/create_cluster.sh [КІЛЬКІСТЬ_ВОРКЕРІВ]
#
# Створює:
#   parcs-master            - майстер (веб-інтерфейс на порту 8080)
#   parcs-worker-1..N       - воркери (без зовнішніх IP, інтернет через Cloud NAT)
# Кожна ВМ - Container-Optimized OS, PARCS запускається в Docker-контейнері
# hummer12007/parcs-node з --net=host.
set -euo pipefail

NUM_WORKERS="${1:-6}"
ZONE="${ZONE:-europe-west1-c}"
REGION="${ZONE%-*}"
MACHINE="${MACHINE:-n1-standard-1}"
IMAGE="hummer12007/parcs-node"

PROJECT="$(gcloud config get-value project 2>/dev/null || true)"
if [ -z "$PROJECT" ]; then
  echo "Спочатку оберіть проєкт:  gcloud config set project ВАШ_PROJECT_ID"
  exit 1
fi

if [ -z "${MY_IP:-}" ]; then
  echo "Веб-інтерфейс PARCS дозволяє запускати будь-який код, тому доступ до нього"
  echo "відкриємо лише з вашого IP. Відкрийте в браузері https://ifconfig.me"
  read -rp "і вставте сюди ваш IP: " MY_IP
fi
CLOUDSHELL_IP="$(curl -s -m 10 https://ifconfig.me || true)"
SOURCES="${MY_IP}/32"
[ -n "$CLOUDSHELL_IP" ] && SOURCES="${SOURCES},${CLOUDSHELL_IP}/32"

echo "== Проєкт: $PROJECT | зона: $ZONE | тип ВМ: $MACHINE | воркерів: $NUM_WORKERS"

echo "== Вмикаю Compute Engine API (може зайняти хвилину)..."
gcloud services enable compute.googleapis.com
gcloud config set compute/zone "$ZONE" >/dev/null
gcloud config set compute/region "$REGION" >/dev/null

echo "== Правила firewall..."
if ! gcloud compute firewall-rules describe parcs-internal >/dev/null 2>&1; then
  gcloud compute firewall-rules create parcs-internal --network=default \
    --allow=tcp,udp,icmp --source-tags=parcs --target-tags=parcs \
    --description="PARCS: master <-> workers (Pyro4, HTTP)"
fi
if gcloud compute firewall-rules describe parcs-web >/dev/null 2>&1; then
  gcloud compute firewall-rules update parcs-web --source-ranges="$SOURCES"
else
  gcloud compute firewall-rules create parcs-web --network=default \
    --allow=tcp:8080 --source-ranges="$SOURCES" --target-tags=parcs-master \
    --description="PARCS web UI"
fi

echo "== Cloud NAT (щоб воркери без зовнішніх IP могли завантажити Docker-образ)..."
if ! gcloud compute routers describe parcs-router --region="$REGION" >/dev/null 2>&1; then
  gcloud compute routers create parcs-router --network=default --region="$REGION"
fi
if ! gcloud compute routers nats describe parcs-nat --router=parcs-router --region="$REGION" >/dev/null 2>&1; then
  gcloud compute routers nats create parcs-nat --router=parcs-router --region="$REGION" \
    --auto-allocate-nat-external-ips --nat-all-subnet-ip-ranges
fi

startup_script() {
  # $1 = аргументи PARCS: "master" або "worker <IP майстра>"
  cat <<EOF
#!/bin/bash
# COS за замовчуванням блокує всі вхідні з'єднання, крім SSH. Доступ обмежує firewall GCP.
iptables -w -I INPUT 1 -j ACCEPT
until docker info >/dev/null 2>&1; do sleep 2; done
docker rm -f parcs >/dev/null 2>&1 || true
until docker pull ${IMAGE}; do sleep 5; done
docker run -d --name parcs --restart=always --net=host -e PARCS_ARGS="$1" ${IMAGE}
EOF
}

COMMON=(--machine-type="$MACHINE" --image-family=cos-stable --image-project=cos-cloud
        --boot-disk-size=20GB)

TMPDIR_PARCS="$(mktemp -d)"
startup_script master > "$TMPDIR_PARCS/master.sh"

echo "== Створюю майстер..."
if ! gcloud compute instances describe parcs-master >/dev/null 2>&1; then
  gcloud compute instances create parcs-master "${COMMON[@]}" \
    --tags=parcs,parcs-master \
    --metadata-from-file=startup-script="$TMPDIR_PARCS/master.sh"
fi
MASTER_INT="$(gcloud compute instances describe parcs-master --format='get(networkInterfaces[0].networkIP)')"
MASTER_EXT="$(gcloud compute instances describe parcs-master --format='get(networkInterfaces[0].accessConfigs[0].natIP)')"

startup_script "worker $MASTER_INT" > "$TMPDIR_PARCS/worker.sh"

WORKERS=()
for i in $(seq 1 "$NUM_WORKERS"); do
  name="parcs-worker-$i"
  gcloud compute instances describe "$name" >/dev/null 2>&1 || WORKERS+=("$name")
done
if [ ${#WORKERS[@]} -gt 0 ]; then
  echo "== Створюю воркери: ${WORKERS[*]}"
  gcloud compute instances create "${WORKERS[@]}" "${COMMON[@]}" \
    --no-address --tags=parcs \
    --metadata-from-file=startup-script="$TMPDIR_PARCS/worker.sh"
fi

echo "== Чекаю, поки PARCS запуститься і воркери зареєструються (зазвичай 2-4 хв)..."
for _ in $(seq 1 60); do
  n="$(curl -s -m 5 "http://$MASTER_EXT:8080/api/worker" | grep -o '"id"' | wc -l || true)"
  echo "   зареєстровано воркерів: ${n:-0} / $NUM_WORKERS"
  [ "${n:-0}" -ge "$NUM_WORKERS" ] && break
  sleep 10
done

echo
echo "Готово. Веб-інтерфейс PARCS:  http://$MASTER_EXT:8080"
echo "  Workers - список воркерів (кнопки Enable/Disable)"
echo "  Add Job - завантажити solutions/*.py та inputs/*.txt"
echo
echo "Автоматичний бенчмарк:  python3 tools/benchmark.py http://$MASTER_EXT:8080"
echo "Після роботи ОБОВ'ЯЗКОВО видаліть кластер:  bash deploy/delete_cluster.sh"
