"""
Provide a wrapper for dials.rescale_diamond_anvil_cell.

When performing a high-pressure data collection using a diamond anvil pressure cell,
the incident and diffracted beams are attenuated in passing through the anvils,
adversely affecting the scaling statistics.  dials.rescale_diamond_anvil_cell
provides a correction to the integrated intensities before symmetry determination and
scaling.

This wrapper is intended for use in the _integrate_finish step of the DialsIntegrater.
"""

from __future__ import absolute_import, division, print_function

from xia2.Driver.DriverFactory import DriverFactory

import os

try:
    from typing import List, Optional, SupportsFloat, Tuple
except ImportError:
    pass


def rescale_dac(driver_type=None):
    """A factory for RescaleDACWrapper classes."""

    driver_instance = DriverFactory.Driver(driver_type)

    class RescaleDACWrapper(driver_instance.__class__):
        """Wrap dials.rescale_diamond_anvil_cell."""

        def __init__(self):
            super(RescaleDACWrapper, self).__init__()

            self.set_executable("dials.rescale_diamond_anvil_cell")

            # Input and output files.
            # None is a valid value only for the output experiment list filename.
            self.experiments_filenames = []  # type: List[str, ...]
            self.reflections_filenames = []  # type: List[str, ...]
            self.output_experiments_filename = None  # type: Optional[str]
            self.output_reflections_filename = None  # type: Optional[str]

            # Parameters to pass to dials.rescale_diamond_anvil_cell
            self.density = None  # type: Optional[SupportsFloat]
            self.thickness = None  # type: Optional[SupportsFloat]
            self.normal = None  # type: Optional[Tuple[3 * (SupportsFloat,)]]

        def __call__(self):
            """Run dials.rescale_diamond_anvil_cell if the parameters are valid."""
            # We should only start if the properties have been set.
            assert self.experiments_filenames
            assert self.reflections_filenames
            # None is a valid value for the output experiment list filename.
            assert self.output_reflections_filename
            assert self.density
            assert self.thickness
            assert self.normal

            self.add_command_line(self.experiments_filenames)
            self.add_command_line(self.reflections_filenames)
            if self.output_experiments_filename:
                self.add_command_line(
                    "output.experiments=%s" % self.output_experiments_filename
                )
            self.add_command_line(
                "output.reflections=%s" % self.output_reflections_filename
            )
            self.add_command_line("anvil.density=%s" % self.density)
            self.add_command_line("anvil.thickness=%s" % self.thickness)
            self.add_command_line("anvil.normal=%s,%s,%s" % tuple(self.normal))

            self.start()
            self.close_wait()
            self.check_for_errors()

            assert os.path.exists(self.output_reflections_filename)

    return RescaleDACWrapper()
