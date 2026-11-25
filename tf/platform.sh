# JDTF v1: accept only converted board-specific images. Never write MTD.
REQUIRE_IMAGE_METADATA=0
RAMFS_COPY_BIN='/sbin/jdtf-image mount umount mkdir rm tar sync'
RAMFS_COPY_DATA='/etc/jdtf-root'

platform_check_image() {
    [ "$(board_name)" = 'jdcloud,re-cp-02' ] || return 1
    [ -f /etc/jdtf-root ] || return 1
    /sbin/jdtf-image check "$1"
}

platform_do_upgrade() {
    local mnt=/tmp/jdtf-config
    /sbin/jdtf-image check "$1" || exit 1
    /sbin/jdtf-image layout /dev/mmcblk0 || exit 1
    # Stage2 runs from RAM. Clear the old software overlay, retain /overlay/data,
    # and restore only the configuration selected by standard sysupgrade.
    mkdir -p "$mnt"
    mount -t ext4 /dev/mmcblk0p3 "$mnt" || exit 1
    rm -rf "$mnt/upper" "$mnt/work" || exit 1
    mkdir -p "$mnt/upper" "$mnt/work"
    if [ -n "$UPGRADE_BACKUP" ]; then
        tar xzf "$UPGRADE_BACKUP" -C "$mnt/upper" || exit 1
    fi
    /sbin/jdtf-image generation "$1" >"$mnt/.jdtf-generation" || exit 1
    sync
    umount "$mnt" || exit 1
    /sbin/jdtf-image install "$1" /dev/mmcblk0 || exit 1
}

platform_copy_config() { return 0; }
