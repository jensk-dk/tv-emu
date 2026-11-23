SUMMARY = "RDK-E's middleware on the virtual machine: its whole package group, with this layer's vendor components"
DESCRIPTION = "What RDK-E's middleware-test-image is for a device: packagegroup-middleware-layer, here with \
packagegroup-hal-tvemu as the vendor side, Westeros with its backend for the VM's display, and the emulator's \
remote control. Built with rdke/build.sh --middleware. No application layer: no browser and no user interface."

require recipes-core/images/core-image-minimal.bb

IMAGE_INSTALL:append = " \
    packagegroup-middleware-layer \
    packagegroup-hal-tvemu \
    westeros \
    westeros-soc-drm \
    libegl-mesa libgles2-mesa libgbm mesa-megadriver \
    tvemu-remote \
    tvemu-device \
    "

IMAGE_ROOTFS_EXTRA_SPACE = "262144"

# Dobby, the container daemon, reads /etc/dobby.json. The middleware's recipe
# installs its settings as /etc/dobby.generic.json and leaves it to the image
# to give them that name unless a vendor layer has brought its own, as RDK-E's
# middleware-test-image does. Without the file Dobby ends with a segmentation
# fault at start: its default settings have no GPU and VPU part, and it prints
# them.
dobby_generic_config_patch () {
    if [ -f "${IMAGE_ROOTFS}/etc/dobby.generic.json" ]; then
        if [ -f "${IMAGE_ROOTFS}/etc/dobby.json" ]; then
            rm ${IMAGE_ROOTFS}/etc/dobby.generic.json
        else
            mv ${IMAGE_ROOTFS}/etc/dobby.generic.json ${IMAGE_ROOTFS}/etc/dobby.json
        fi
    fi
}
ROOTFS_POSTPROCESS_COMMAND += "dobby_generic_config_patch; "

# The SSH server (dropbear.service). RDK's start script for it ends with
# "DROPBEAR_RSAKEY_DIR is not set" unless /etc/default/dropbear names the
# directory of the host key, and the unit that makes the key is to make it
# there and not look for it in /etc and /var. A vendor layer does both for its
# images; these are the two steps of the Pi's (meta-vendor-raspberrypi-release,
# conf/machine/include/vendor.inc), with its directory.
DROPBEAR_RSAKEY_DIR ?= "/opt/dropbear"

update_dropbearkey_to_rw_path () {
    if [ -f "${IMAGE_ROOTFS}/lib/systemd/system/dropbearkey.service" ]; then
        sed -i '/\/var/d; /\/var\/lib/d;/\/etc\/dropbear/d' ${IMAGE_ROOTFS}/lib/systemd/system/dropbearkey.service
    fi
}

override_dropbear_rsakey_dir () {
    dropbear_conf="${IMAGE_ROOTFS}/etc/default/dropbear"
    if [ -f "$dropbear_conf" ]; then
        if grep -q '^DROPBEAR_RSAKEY_DIR=' "$dropbear_conf"; then
            sed -i "s|^DROPBEAR_RSAKEY_DIR=.*|DROPBEAR_RSAKEY_DIR=\"${DROPBEAR_RSAKEY_DIR}\"|" "$dropbear_conf"
        else
            echo "DROPBEAR_RSAKEY_DIR=\"${DROPBEAR_RSAKEY_DIR}\"" >> "$dropbear_conf"
        fi
    fi
}
ROOTFS_POSTPROCESS_COMMAND += "update_dropbearkey_to_rw_path; override_dropbear_rsakey_dir; "

# The Bluetooth manager (btmgr.service) is not started. The VM has no
# Bluetooth controller and its kernel no Bluetooth, so the service ended with
# "Could not initialize BTRCore/HAL module" and was started again for as long
# as the VM ran. Its package stays: the Bluetooth plug-in and the remote
# control manager link against its library. The package's preset is what
# enables the unit when the image is put together, so the preset is changed
# as well as the link removed.
tvemu_no_btmgr_start () {
    preset="${IMAGE_ROOTFS}${systemd_unitdir}/system-preset/98-bluetooth-mgr.preset"
    if [ -f "$preset" ]; then
        echo "disable btmgr.service" > "$preset"
    fi
    rm -f ${IMAGE_ROOTFS}${sysconfdir}/systemd/system/multi-user.target.wants/btmgr.service
}
ROOTFS_POSTPROCESS_COMMAND += "tvemu_no_btmgr_start; "
