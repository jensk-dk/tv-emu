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

# Thunder listens on every address of the target, not on its loopback address
# alone, as RDK-E's middleware-test-image has it for development images. The
# VM's network is QEMU's own (user mode): nothing reaches the target unless
# the launcher forwards a port to it, which it does from this host's loopback
# address and only when asked (--option forward=9998:9998).
wpeframework_binding_patch () {
    if [ -f "${IMAGE_ROOTFS}/etc/WPEFramework/config.json" ]; then
        sed -i "s/127.0.0.1/0.0.0.0/g" ${IMAGE_ROOTFS}/etc/WPEFramework/config.json
    fi
}
ROOTFS_POSTPROCESS_COMMAND += "wpeframework_binding_patch; "

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

# A journal that holds a whole start. RDK-E keeps 3 MB of it in memory, in two
# files, which the middleware's services fill in less than a minute: what a
# unit did at start-up was gone before anyone could ask. A target for
# development keeps 64 MB (the VM has 2 GB of memory unless a run says
# otherwise).
tvemu_journal_size () {
    conf="${IMAGE_ROOTFS}${sysconfdir}/systemd/journald.conf"
    if [ -f "$conf" ]; then
        sed -i -e 's/^RuntimeMaxUse=.*/RuntimeMaxUse=64M/' -e 's/^RuntimeMaxFileSize=.*/RuntimeMaxFileSize=16M/' \
            -e 's/^RuntimeMaxFiles=.*/RuntimeMaxFiles=4/' "$conf"
    fi
}
ROOTFS_POSTPROCESS_COMMAND += "tvemu_journal_size; "

# One SSH server, not two. The image had both of dropbear's units enabled:
# RDK's dropbear.service, which listens all the time, and openembedded-core's
# dropbear.socket, with which systemd listens on port 22 and starts a server
# for each connection. The service's unit says that it conflicts with the
# socket, so starting it closes the socket, but at start-up the service was
# seen to end with "Failed listening on '22': Address already in use" in at
# least four boots of eight (2026-11-24), and to start at the retry five
# seconds later. The socket unit is not enabled; the package's preset is
# changed as well as the link removed, as for the Bluetooth manager below.
tvemu_no_dropbear_socket () {
    preset="${IMAGE_ROOTFS}${systemd_unitdir}/system-preset/98-dropbear.preset"
    if [ -f "$preset" ]; then
        sed -i 's/^enable dropbear.socket/disable dropbear.socket/' "$preset"
    fi
    rm -f ${IMAGE_ROOTFS}${sysconfdir}/systemd/system/sockets.target.wants/dropbear.socket
}
ROOTFS_POSTPROCESS_COMMAND += "tvemu_no_dropbear_socket; "

# The client of the operator's cloud (parodus, for WebPA) is not started. It
# is given the address of its server by the device's configuration, and a
# virtual device has none: it ended with "Bad webpa url" and an abort
# (signal 6) at start and was started again every 40 seconds for as long as
# the VM ran. Seen on 2026-11-24, when the journal first held a whole start.
tvemu_no_parodus_start () {
    for preset in ${IMAGE_ROOTFS}${systemd_unitdir}/system-preset/98-sysint.preset \
                  ${IMAGE_ROOTFS}${systemd_unitdir}/system-preset/98-tr69hostif.preset; do
        if [ -f "$preset" ]; then
            sed -i -e 's/^enable \(parodus\.service\|parodus_bsp\.path\|restart-parodus\.path\|restart-parodus\.service\)$/disable \1/' "$preset"
        fi
    done
    for unit in parodus.service parodus_bsp.path restart-parodus.path restart-parodus.service; do
        find ${IMAGE_ROOTFS}${sysconfdir}/systemd/system -name "$unit" -type l -delete
    done
}
ROOTFS_POSTPROCESS_COMMAND += "tvemu_no_parodus_start; "

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
