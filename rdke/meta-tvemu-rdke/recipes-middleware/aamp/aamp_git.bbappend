# RDK-E's configuration for bolt apps (rdke-rdkm-config.inc) takes the
# features "webkitbrowser-plugin" and "build_external_player_interface" away,
# and with them AAMP's bindings for the browser and the library AAMP is linked
# against (the player interface). This image has the browser plug-in, and its
# user interface plays video with AAMP, so both are named here.
DEPENDS:append:tvemu = " player-interface ${WPEWEBKIT}"
RDEPENDS:${PN}:append:tvemu = " player-interface"
EXTRA_OECMAKE:append:tvemu = " -DCMAKE_WPEWEBKIT_JSBINDINGS=1"
# AAMP's bindings print sizes with "%d", which is right for a 32-bit program
# (RDK-E's own arrangement) and a warning in a 64-bit one, and AAMP's build
# makes that warning an error after the flags a recipe can give.
do_configure:prepend:tvemu() {
    sed -i 's/ -Werror=format / /' ${S}/CMakeLists.txt
}
