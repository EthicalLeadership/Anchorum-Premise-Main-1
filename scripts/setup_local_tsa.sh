#!/usr/bin/env bash
#
# Provision the local RFC 3161 Timestamp Authority used by
# interface/ledger/timestamp.py.
#
# Why this script exists at all: nothing in the repository generated these
# certificates, yet timestamp.py tells you to "Run the setup script." This is
# that script.
#
# The subtle part is the signer certificate's extensions. OpenSSL's `ts -reply`
# refuses a signer certificate that does not assert the timeStamping extended
# key usage, with:
#
#   TS_RESP_CTX_set_signer_cert:invalid signer certificate purpose
#
# A certificate issued under the CA profile carries basicConstraints CA:true and
# keyUsage certSign/cRLSign, and no extendedKeyUsage. That is a CA certificate,
# not a timestamping certificate, and it is exactly what the error above means.
# The fix is to issue the signer with a dedicated profile and an explicit
# -extensions flag, rather than letting [CA_default] x509_extensions decide.
#
# Usage:
#   bash scripts/setup_local_tsa.sh            # create if absent
#   FORCE=1 bash scripts/setup_local_tsa.sh    # wipe and regenerate
#
set -euo pipefail

TSA_DIR="${1:-var/tsa}"

if [ -e "$TSA_DIR/ca.key" ] && [ "${FORCE:-0}" != "1" ]; then
    echo "ABORT: $TSA_DIR is already provisioned." >&2
    echo "       Re-run with FORCE=1 to wipe and regenerate." >&2
    exit 1
fi

echo "Provisioning TSA in $TSA_DIR"
rm -rf "$TSA_DIR"
mkdir -p "$TSA_DIR/newcerts"
: > "$TSA_DIR/index.txt"
echo 1000 > "$TSA_DIR/serial"
echo 01 > "$TSA_DIR/tsaserial"

# The config is written here rather than kept as a tracked file so that the
# `dir` entry always matches wherever the caller asked for the store to live.
cat > "$TSA_DIR/tsa.cnf" <<'CNF'
[ ca ]
default_ca = CA_default

[ CA_default ]
dir              = @TSA_DIR@
database         = $dir/index.txt
new_certs_dir    = $dir/newcerts
certificate      = $dir/ca.crt
serial           = $dir/serial
private_key      = $dir/ca.key
default_md       = sha256
policy           = policy_any
email_in_dn      = no
name_opt         = ca_default
cert_opt         = ca_default
copy_extensions  = none
# Used for CA self-signing and any ordinary leaf. The TSA signer overrides this
# on the command line with -extensions tsa_cert.
x509_extensions  = v3_ca

[ policy_any ]
commonName             = supplied
countryName            = optional
stateOrProvinceName    = optional
organizationName       = optional
organizationalUnitName = optional
emailAddress           = optional

[ req ]
distinguished_name = req_distinguished_name

[ req_distinguished_name ]

[ v3_ca ]
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid:always,issuer
basicConstraints = critical, CA:true
keyUsage = critical, digitalSignature, cRLSign, keyCertSign

# The timestamping signer profile. Both keyUsage and extendedKeyUsage are
# critical, and CA:FALSE is explicit: a TSA signer must not be a CA.
[ tsa_cert ]
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid:always,issuer
basicConstraints = critical, CA:FALSE
keyUsage = critical, digitalSignature, nonRepudiation
extendedKeyUsage = critical, timeStamping

[ tsa ]
default_tsa = tsa_config1

[ tsa_config1 ]
dir                     = @TSA_DIR@
serial                  = $dir/tsaserial
crypto_device           = builtin
signer_cert             = $dir/tsa.crt
certs                   = $dir/ca.crt
signer_key              = $dir/tsa.key
signer_digest           = sha256
default_policy          = 1.2.3.4.1
other_policies          = 1.2.3.4.2
digests                 = sha256, sha512
accuracy                = secs:1
ordering                = yes
tsa_name                = yes
ess_cert_id_chain       = no
ess_cert_id_alg         = sha256
CNF

# `dir` is relative in the OpenSSL config, so substitute the caller's path.
sed -i "s|@TSA_DIR@|$TSA_DIR|g" "$TSA_DIR/tsa.cnf"

echo "  generating CA key and self-signed certificate"
openssl genrsa -out "$TSA_DIR/ca.key" 2048 2>/dev/null
chmod 600 "$TSA_DIR/ca.key"
openssl req -x509 -new -sha256 -days 3650 \
    -key "$TSA_DIR/ca.key" \
    -subj "/CN=Anchorum Local TSA Root" \
    -config "$TSA_DIR/tsa.cnf" \
    -extensions v3_ca \
    -out "$TSA_DIR/ca.crt" 2>/dev/null

echo "  generating TSA signer key and CSR"
openssl genrsa -out "$TSA_DIR/tsa.key" 2048 2>/dev/null
chmod 600 "$TSA_DIR/tsa.key"
openssl req -new -sha256 \
    -key "$TSA_DIR/tsa.key" \
    -subj "/CN=Anchorum Local TSA Signer" \
    -config "$TSA_DIR/tsa.cnf" \
    -out "$TSA_DIR/tsa.csr" 2>/dev/null

echo "  issuing the signer under the tsa_cert profile"
openssl ca -batch -notext \
    -config "$TSA_DIR/tsa.cnf" \
    -extensions tsa_cert \
    -days 3650 \
    -in "$TSA_DIR/tsa.csr" \
    -out "$TSA_DIR/tsa.crt" 2>/dev/null

rm -f "$TSA_DIR/tsa.csr" "$TSA_DIR/index.txt.old" "$TSA_DIR/index.txt.attr.old"

# Assert the property OpenSSL is strict about, rather than trusting the flags.
if ! openssl x509 -in "$TSA_DIR/tsa.crt" -noout -text | grep -q "Time Stamping"; then
    echo "ABORT: signer certificate has no timeStamping extended key usage." >&2
    openssl x509 -in "$TSA_DIR/tsa.crt" -noout -text | sed -n '/X509v3 extensions/,/Signature Algorithm/p' >&2
    exit 1
fi

if openssl x509 -in "$TSA_DIR/tsa.crt" -noout -text | grep -q "CA:TRUE"; then
    echo "ABORT: signer certificate is a CA certificate; OpenSSL will refuse it." >&2
    exit 1
fi

echo "TSA ready:"
echo "  signer : $TSA_DIR/tsa.crt (EKU: critical timeStamping, CA:FALSE)"
echo "  CA     : $TSA_DIR/ca.crt"
echo "  config : $TSA_DIR/tsa.cnf"
