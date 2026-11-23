# The x86-64 machine: the package group has Ne10 built, a library of
# functions written for ARM's NEON instructions, whose recipe is for ARM
# machines only. Nothing in the image needs it there.
DEPENDS:remove:x86-64 = "ne10"
