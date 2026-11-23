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
