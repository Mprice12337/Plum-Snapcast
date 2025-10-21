#!/bin/bash
set -e

CERT_DIR="/app/certs"
mkdir -p "${CERT_DIR}"

if [ -f "${CERT_DIR}/snapserver.crt" ] && [ -f "${CERT_DIR}/snapserver.key" ]; then
    echo "[CERTS] SSL certificates already exist, skipping generation"
    exit 0
fi

echo "[CERTS] Generating self-signed SSL certificates..."

# Generate CA
openssl req -x509 -newkey rsa:2048 \
    -keyout "${CERT_DIR}/ca.key" \
    -out "${CERT_DIR}/ca.crt" \
    -days 3650 -nodes \
    -subj "/CN=Snapcast CA"

# Generate server key
openssl genrsa -out "${CERT_DIR}/snapserver.key" 2048

# Create certificate signing request
openssl req -new \
    -key "${CERT_DIR}/snapserver.key" \
    -out "${CERT_DIR}/snapserver.csr" \
    -subj "/CN=${CERT_SERVER_CN}"

# Create extension file for SAN
cat > "${CERT_DIR}/san.ext" << EOF
subjectAltName = DNS:${CERT_SERVER_DNS// /,DNS:}
EOF

# Sign the certificate
openssl x509 -req \
    -in "${CERT_DIR}/snapserver.csr" \
    -CA "${CERT_DIR}/ca.crt" \
    -CAkey "${CERT_DIR}/ca.key" \
    -CAcreateserial \
    -out "${CERT_DIR}/snapserver.crt" \
    -days 3650 \
    -extfile "${CERT_DIR}/san.ext"

# Cleanup
rm -f "${CERT_DIR}/snapserver.csr" "${CERT_DIR}/san.ext"

echo "[CERTS] ✅ SSL certificates generated successfully"