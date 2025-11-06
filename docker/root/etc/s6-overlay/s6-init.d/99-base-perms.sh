#!/command/with-contenv bash
    # ==============================================================================
    # S6-overlay init script to ensure correct ownership of persistent volumes.
    # ==============================================================================

    echo "Ensuring /config and /data directories are owned by user abc..."
    chown -R abc:abc /config /data || echo "Warning: Could not chown /config or /data. This might be okay if the volume is mounted with specific user."

    echo "Permissions set."