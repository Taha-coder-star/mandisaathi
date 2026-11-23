#!/bin/sh
# Task 1.4 DONE check: all 3 roles start from the same image. Used by CI; runs locally in Git Bash too.
set -eu
IMG=${1:-mandisaathi}
trap 'docker rm -f smoke-web smoke-worker >/dev/null 2>&1 || true' EXIT

echo "== batch"
docker run --rm "$IMG" python -m mandi.batch

echo "== web"
docker run -d --name smoke-web -p 8000:8000 "$IMG" >/dev/null
ok=
for _ in $(seq 20); do
  if curl -fs localhost:8000/health; then ok=1; break; fi
  sleep 1
done
[ -n "$ok" ] || { docker logs smoke-web; echo "web: /health never returned 200"; exit 1; }
echo

echo "== worker"
docker run -d --name smoke-worker "$IMG" python -m app.worker >/dev/null
sleep 5
docker logs smoke-worker | grep -q "worker ready" || { docker logs smoke-worker; echo "worker: no ready line"; exit 1; }
[ "$(docker inspect -f '{{.State.Running}}' smoke-worker)" = true ] || { echo "worker: exited"; exit 1; }

echo "all 3 roles OK from image $IMG"
