#!/bin/sh
# BOUNDARY PROOF (V2.1 §4) -- runs inside the `proof` container: stock alpine:3.20,
# no ACT code, no Python, on the egress-deny network. Uses busybox wget/nc/nslookup
# only. Every attempt records the exact failure text. ACT is not in the path of any
# deny-proof; the allow-proofs touch lab services directly, not through ACT.
OUT=/lab/run/results/boundary_proof.txt
mkdir -p /lab/run/results
: > "$OUT"
log() { echo "$*" | tee -a "$OUT"; }
try() {  # try <label> <url>  -> records status line
  label="$1"; url="$2"
  res=$(wget -q -O - -T 5 "$url" 2>&1); rc=$?
  log "[$label] $url -> rc=$rc $(echo "$res" | tr '\n' ' ' | cut -c1-140)"
}
tcp() {  # tcp <label> <host> <port>
  res=$(nc -z -w 5 "$2" "$3" 2>&1); rc=$?
  log "[$1] tcp $2:$3 -> rc=$rc $(echo "$res" | tr '\n' ' ' | cut -c1-120)"
}
log "=== boundary proof from $(hostname) at $(date -u +%FT%TZ) ==="
log "container routes:"; ip route 2>/dev/null | tee -a "$OUT"
log "container addresses:"; ip -4 addr show 2>/dev/null | grep inet | tee -a "$OUT"
log "--- 1. DENY external host ---"
try  "1a external https" "https://example.com/"
try  "1b external http"  "http://example.com/"
tcp  "1c external ip"    1.1.1.1 443
tcp  "1d external ip"    8.8.8.8 53
log "--- 2. DENY host services ---"
tcp  "2a host.docker.internal:8000 (dev ACT API on the host)" host.docker.internal 8000
tcp  "2b host.docker.internal:5432 (dev Postgres on the host)" host.docker.internal 5432
[ -n "$HOST_IP" ] && tcp "2c host LAN ip:8000" "$HOST_IP" 8000
[ -n "$HOST_IP" ] && tcp "2d host LAN ip:5432" "$HOST_IP" 5432
log "--- 3. DENY cloud-metadata-shaped addresses ---"
try  "3a aws/gcp/azure imds" "http://169.254.169.254/latest/meta-data/"
try  "3b azure imds ip"      "http://169.254.169.254/metadata/instance"
tcp  "3c link-local tcp"     169.254.169.254 80
try  "3d gcp metadata name"  "http://metadata.google.internal/computeMetadata/v1/"
log "--- 4. ALLOW lab-owned destinations ---"
try  "4a attacker-sim"       "http://canary:8825/any"
try  "4b canary metadata DECOY (lab-owned, distinguishable)" "http://canary:8824/latest/meta-data/"
try  "4c object store"       "http://canary:8821/objects"
try  "4d mcp trusted manifest" "http://mcp_trusted:8831/manifest"
try  "4e mcp risky manifest" "http://mcp_risky:8833/manifest"
tcp  "4f lab_db"             lab_db 5432
try  "4g registry"           "http://registry:8811/agents"
try  "4h act (may be STOPPED during the independence run)" "http://act:8802/docs"
log "--- 6. DNS behaviour ---"
res=$(nslookup example.com 2>&1); log "[6a nslookup example.com] rc=$? $(echo "$res" | tr '\n' ' ' | cut -c1-200)"
res=$(nslookup canary 2>&1);      log "[6b nslookup canary] rc=$? $(echo "$res" | tr '\n' ' ' | cut -c1-160)"
res=$(cat /etc/resolv.conf 2>&1); log "[6c resolv.conf] $(echo "$res" | tr '\n' ' ')"
log "=== end ==="
