#/usr/bin/env python
# Flags.py
#   Copyright (C) 2006 CCLRC, Graeme Winter
#
#   This code is distributed under the BSD license, a copy of which is
#   included in the root directory of this package.
#
# 4th May 2007
#
# A singleton to handle flags, which can be imported more easily
# as it will not suffer the problems with circular references that
# the CommandLine singleton suffers from. FIXME xia2-42 this is due
# for retirement & working into the Phil structure

import os
import sys

from xia2.Handlers.Environment import get_number_cpus

class _Flags(object):
  '''A singleton to manage boolean flags.'''

  def __init__(self):
    self._quick = False

    # XDS specific things - to help with handling tricky data sets

    self._xparm = None
    self._xparm_beam_vector = None
    self._xparm_rotation_axis = None
    self._xparm_origin = None

    self._xparm_a = None
    self._xparm_b = None
    self._xparm_c = None

    # starting directory (to allow setting working directory && relative
    # paths on input)
    self._starting_directory = os.getcwd()

    return

  def get_starting_directory(self):
    return self._starting_directory

  def set_quick(self, quick):
    self._quick = quick
    return

  def get_quick(self):
    return self._quick

  def set_xparm(self, xparm):

    self._xparm = xparm

    from xia2.Wrappers.XDS.XDS import xds_read_xparm

    xparm_info = xds_read_xparm(xparm)

    self._xparm_origin = xparm_info['ox'], xparm_info['oy']
    self._xparm_beam_vector = tuple(xparm_info['beam'])
    self._xparm_rotation_axis = tuple(xparm_info['axis'])
    self._xparm_distance = xparm_info['distance']

    return

  def get_xparm(self):
    return self._xparm

  def get_xparm_origin(self):
    return self._xparm_origin

  def get_xparm_rotation_axis(self):
    return self._xparm_rotation_axis

  def get_xparm_beam_vector(self):
    return self._xparm_beam_vector

  def get_xparm_distance(self):
    return self._xparm_distance

  def set_xparm_ub(self, xparm):

    self._xparm_ub = xparm

    tokens = map(float, open(xparm, 'r').read().split())

    self._xparm_a = tokens[-9:-6]
    self._xparm_b = tokens[-6:-3]
    self._xparm_c = tokens[-3:]

    return

  def get_xparm_a(self):
    return self._xparm_a

  def get_xparm_b(self):
    return self._xparm_b

  def get_xparm_c(self):
    return self._xparm_c

  def set_freer_file(self, freer_file):

    # mtzdump this file to make sure that there is a FreeR_flag
    # column therein...

    freer_file = os.path.abspath(freer_file)

    if not os.path.exists(freer_file):
      raise RuntimeError, '%s does not exist' % freer_file

    from xia2.Modules.FindFreeFlag import FindFreeFlag
    from xia2.Handlers.Streams import Debug

    column = FindFreeFlag(freer_file)

    Debug.write('FreeR_flag column in %s found: %s' % \
                (freer_file, column))

    self._freer_file = freer_file
    return

Flags = _Flags()
