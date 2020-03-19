import sys

if sys.version_info.major < 3:
    print("")
    print("!" * 70)
    print("")
    print("This version of xia2 no longer supports Python 2.")
    print("Please choose one of the following options:")
    print("")
    print("1. upgrade your environment to a supported version of Python 3,")
    print("")
    print("2. switch to a version of xia2 that supports Python 2 by running")
    print("     cd $(libtbx.find_in_repositories xia2)")
    print("     git checkout dials-2.2")
    print("")
    print("or")
    print("")
    print("3. remove xia2 from your cctbx environment by running")
    print("     cd $(libtbx.show_build_path)")
    print("     libtbx.configure --exclude=xia2 .")
    print("")
    print("!" * 70)
    exit(1)

import dials.precommitbx.nagger
from xia2.XIA2Version import Version

dials.precommitbx.nagger.nag()

# the import implicitly updates the .gitversion file
print(Version)
