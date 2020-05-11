from __future__ import absolute_import, division, print_function

import sys
import warnings

if sys.version_info.major == 2:
    warnings.warn(
        "Python 2 is no longer fully supported. Please consider using the DIALS 2.2 release branch. "
        "For more information on Python 2.7 support please go to https://github.com/dials/dials/issues/1175.",
        DeprecationWarning,
    )
