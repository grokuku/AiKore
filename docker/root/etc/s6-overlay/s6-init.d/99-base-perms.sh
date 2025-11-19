#!/command/with-contenv bash
# ==============================================================================
# S6-overlay init script to ensure correct ownership of persistent volumes.
# ==============================================================================

echo "Ensuring /config directory is owned by user abc..."
# /config is critical (DB, logs) and usually small. Recursive is safe and recommended.
chown -R abc:abc /config || echo "Warning: Could not chown /config."

echo "Ensuring /data directory root is owned by user abc..."
# /data often contains massive model libraries. Recursive chown here causes
# massive delays (10+ mins). We only chown the root mount point to allow writing.
chown abc:abc /data || echo "Warning: Could not chown /data root. Ensure the volume is mounted with correct permissions."

echo "Permissions set."