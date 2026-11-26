# Called after the TF ext4 partition is mounted. Keep configuration and user
# data, but never carry old kernel modules/software across a web upgrade.
jdtf_migrate_overlay() {
    local lower="$1" overlay="$2" version old item
    version="$(cat "$lower/etc/jdtf-generation")" || return 1
    old="$(cat "$overlay/.jdtf-generation" 2>/dev/null)"
    if [ -n "$old" ] && [ "$old" != "$version" ]; then
        if [ ! -f "$overlay/.jdtf-migration-ready" ]; then
            rm -rf "$overlay/.jdtf-migrate" || return 1
            mkdir -p "$overlay/.jdtf-migrate" || return 1
            for item in etc root; do
                [ ! -d "$overlay/upper/$item" ] || cp -a "$overlay/upper/$item" "$overlay/.jdtf-migrate/" || return 1
            done
            : >"$overlay/.jdtf-migration-ready"
            sync
        fi
        rm -rf "$overlay/upper" "$overlay/work" || return 1
        mkdir -p "$overlay/upper" "$overlay/work" || return 1
        for item in etc root; do
            [ ! -d "$overlay/.jdtf-migrate/$item" ] || cp -a "$overlay/.jdtf-migrate/$item" "$overlay/upper/" || return 1
        done
    fi
    printf '%s\n' "$version" >"$overlay/.jdtf-generation" || return 1
    sync
    rm -rf "$overlay/.jdtf-migrate" "$overlay/.jdtf-migration-ready"
}
