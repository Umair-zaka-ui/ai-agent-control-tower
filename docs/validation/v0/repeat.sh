#!/bin/bash
# V0 §16 — bounded repeatability loop: N consecutive runs of the 5.1 guard + the 5.5 posture suite.
N=${1:-50}
cd /c/Users/PHS/Desktop/ai-agent-control-tower/backend
echo "REPEATABILITY: N=$N, commit $(git rev-parse --short HEAD), branch $(git branch --show-current), start $(date -Iseconds)"
fails=0
for i in $(seq 1 $N); do
  s=$(date +%s)
  out=$(.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider tests/posture/test_security_posture.py "tests/runtime/test_agent_asset_model.py::test_ac09_existing_agents_are_backfilled_native_and_governed" 2>&1)
  rc=$?; e=$(date +%s)
  summ=$(echo "$out" | tail -1)
  echo "run $i rc=$rc dur=$((e-s))s :: $summ"
  if [ $rc -ne 0 ]; then fails=$((fails+1)); echo "$out" | grep -E "^(FAILED|E )" | head -20; fi
done
echo "end $(date -Iseconds) fails=$fails/$N"
