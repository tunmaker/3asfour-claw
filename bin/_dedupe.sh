# Shared write-once guard for the tools that change household state.
#
# Turns were never retried, deliberately: a gateway timeout can still complete
# server-side, and a retry would log the same feed twice. Streaming makes a turn
# more likely to die mid-flight, not less, so the guard has to live in the tools
# rather than in the caller's willingness to retry.
#
# The model composes these command lines, so there is no turn id to thread
# through. Instead the guard is content-based over a short window: the same verb
# with the same arguments inside DEDUPE_WINDOW_SECS is treated as the same write.
#
# The window is deliberately short. "Add milk" twice in a minute is a retry;
# twice in an afternoon is two errands.

DEDUPE_WINDOW_SECS="${DEDUPE_WINDOW_SECS:-90}"
DEDUPE_DIR="${ABBES_DATA_DIR:-/var/lib/abbes}/state"
DEDUPE_FILE="$DEDUPE_DIR/writes.log"

# already_written <tool> <args...> -> 0 if this exact write just happened
already_written() {
    [ "${DEDUPE_WINDOW_SECS}" -gt 0 ] 2>/dev/null || return 1

    local key now cutoff line ts rest
    key=$(printf '%s\0' "$@" | sha256sum | cut -d' ' -f1)
    now=$(date +%s)
    cutoff=$((now - DEDUPE_WINDOW_SECS))

    mkdir -p "$DEDUPE_DIR" 2>/dev/null || return 1
    touch "$DEDUPE_FILE" 2>/dev/null || return 1

    local hit=1
    if [ -r "$DEDUPE_FILE" ]; then
        while IFS=' ' read -r ts rest; do
            [ -n "$ts" ] || continue
            [ "$ts" -ge "$cutoff" ] 2>/dev/null || continue
            [ "$rest" = "$key" ] && hit=0
        done < "$DEDUPE_FILE"
    fi

    # prune while we are here, so the file cannot grow without bound
    local tmp="$DEDUPE_FILE.$$"
    awk -v c="$cutoff" '$1 >= c' "$DEDUPE_FILE" > "$tmp" 2>/dev/null && mv "$tmp" "$DEDUPE_FILE"
    rm -f "$tmp" 2>/dev/null

    [ "$hit" -eq 0 ] && return 0

    printf '%s %s\n' "$now" "$key" >> "$DEDUPE_FILE"
    return 1
}
