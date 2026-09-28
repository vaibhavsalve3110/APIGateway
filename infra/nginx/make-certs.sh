#!/usr/bin/env bash
# Creates a local certificate authority and one wildcard server certificate for *.apigw.localhost.
#
#   ./make-certs.sh          (Git Bash, WSL, macOS, Linux — needs openssl)
#
# Everything lands in infra/docker/certs/, which is git-ignored: these are throwaway development
# certificates and a private key, and none of it may ever be committed or reused outside a laptop.
#
# Browsers reject a self-signed certificate until the CA is trusted. Trusting apigw-local-ca.crt makes
# every *.apigw.localhost name green; the CA key never leaves this folder, but it can sign any name, so
# delete it (and untrust the CA) when you are finished with the stack.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
out="$here/../docker/certs"
mkdir -p "$out"

# Some Windows installers (psqlODBC ships one) set OPENSSL_CONF machine-wide to a file that is not
# there, and every openssl call then fails with "Can't open ... openssl.cnf". Clearing it makes
# openssl fall back to its own built-in configuration, which is what we want anyway.
if [ -n "${OPENSSL_CONF:-}" ] && [ ! -f "$OPENSSL_CONF" ]; then
  echo "note: OPENSSL_CONF points at a missing file ($OPENSSL_CONF) — ignoring it"
  unset OPENSSL_CONF
fi

# Git Bash / MSYS rewrites any argument that looks like a Unix path, so the subject "/C=IN/O=..."
# arrives at openssl as "D:/Projects/Git/C=IN/O=...". Exclude only arguments starting with "/C=",
# which is the subject and nothing else: a blanket exclusion would also stop -keyout and -out being
# translated to Windows paths, and openssl.exe cannot open "/d/Projects/...". Ignored on Linux/macOS.
export MSYS2_ARG_CONV_EXCL='/C='

days_ca=1825
days_leaf=825   # browsers reject leaf certificates valid for longer than ~27 months

if [ -f "$out/server.crt" ] && [ "${1:-}" != "--force" ]; then
  echo "Certificates already exist in $out — pass --force to replace them."
  exit 0
fi

echo "==> local certificate authority"
openssl req -x509 -newkey rsa:4096 -sha256 -days "$days_ca" -nodes \
  -keyout "$out/apigw-local-ca.key" \
  -out "$out/apigw-local-ca.crt" \
  -subj "/C=IN/O=API Gateway Platform/OU=Local development/CN=API Gateway local development CA" \
  -addext "basicConstraints=critical,CA:TRUE,pathlen:0" \
  -addext "keyUsage=critical,keyCertSign,cRLSign"

echo "==> server key and signing request"
openssl req -newkey rsa:2048 -sha256 -nodes \
  -keyout "$out/server.key" \
  -out "$out/server.csr" \
  -subj "/C=IN/O=API Gateway Platform/OU=Local development/CN=apigw.localhost"

# Every name the stack is reached by. A browser ignores the CN and reads only these.
cat > "$out/server.ext" <<EXT
basicConstraints=CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=@names

[names]
DNS.1 = apigw.localhost
DNS.2 = admin.apigw.localhost
DNS.3 = developer.apigw.localhost
DNS.4 = api.apigw.localhost
DNS.5 = sandbox-api.apigw.localhost
DNS.6 = localhost
IP.1  = 127.0.0.1
EXT

echo "==> signing the server certificate"
openssl x509 -req -in "$out/server.csr" -sha256 -days "$days_leaf" \
  -CA "$out/apigw-local-ca.crt" -CAkey "$out/apigw-local-ca.key" -CAcreateserial \
  -extfile "$out/server.ext" \
  -out "$out/server.crt"

rm -f "$out/server.csr" "$out/server.ext" "$out/apigw-local-ca.srl"
chmod 600 "$out"/*.key 2>/dev/null || true

echo
echo "Done. Files in infra/docker/certs/:"
ls -1 "$out"
echo
openssl x509 -in "$out/server.crt" -noout -subject -enddate -ext subjectAltName
echo
cat <<'NEXT'
Next:
  1. Trust infra/docker/certs/apigw-local-ca.crt so browsers stop warning:
       Windows : certutil -user -addstore Root infra\docker\certs\apigw-local-ca.crt
       macOS   : sudo security add-trusted-cert -d -k /Library/Keychains/System.keychain \
                   infra/docker/certs/apigw-local-ca.crt
       Linux   : copy to /usr/local/share/ca-certificates/ and run sudo update-ca-certificates
  2. *.localhost resolves to 127.0.0.1 on its own in Chrome, Edge and Firefox. If a tool on your
     machine does not do this, add the four names to your hosts file.
  3. docker compose --profile app up -d --build
NEXT
