#!/usr/bin/env python
# XDS.py
#   Copyright (C) 2006 CCLRC, Graeme Winter
#
#   This code is distributed under the BSD license, a copy of which is 
#   included in the root directory of this package.
#
# This module is a generic wrapper for the basic components needed to make
# XDS run, including writing the generic header information. This will 
# include the writing of the information from the image header, for instance,
# and should support all image types defined in the Printheader dictionary.
# That is:
# 
# detector_class = {('adsc', 2304, 81):'adsc q4',
#                   ('adsc', 1502, 163):'adsc q4 2x2 binned',
#                   ('adsc', 4096, 51):'adsc q210',
#                   ('adsc', 2048, 102):'adsc q210 2x2 binned',
#                   ('adsc', 6144, 51):'adsc q315',
#                   ('adsc', 3072, 102):'adsc q315 2x2 binned',
#                   ('marccd', 4096, 73):'mar 300',
#                   ('marccd', 3072, 73):'mar 225',
#                   ('marccd', 2048, 79):'mar 165',
#                   ('mar', 2300, 150):'mar 345'}
#
# as of starting this wrapper, 11th December 2006. These detector types
# will map onto standard input records, including the directions of the
# different axes (beam, detector x, detector y) trusted regions of the
# detector (e.g. does the picture go to the corners) and so on.

import os
import sys

if not os.environ.has_key('XIA2CORE_ROOT'):
    raise RuntimeError, 'XIA2CORE_ROOT not defined'

if not os.path.join(os.environ['XIA2CORE_ROOT'], 'Python') in sys.path:
    sys.path.append(os.path.join(os.environ['XIA2CORE_ROOT'], 'Python'))

if not os.environ.has_key('XIA2_ROOT'):
    raise RuntimeError, 'XIA2_ROOT not defined'

if not os.path.join(os.environ['XIA2_ROOT']) in sys.path:
    sys.path.append(os.path.join(os.environ['XIA2_ROOT']))

def header_to_xds(header):
    '''A function to take an input header dictionary from Printheader
    and generate a list of records to start XDS - see Doc/INP.txt.'''

    # --------- mapping tables -------------

    detector_to_detector = {
        'mar':'MAR345',
        'marccd':'CCDCHESS',
        'raxis':'RAXIS',
        'adsc':'ADSC'}

    detector_to_overload = {
        'mar':130000,
        'marccd':65000,
        'raxis':1000000,
        'adsc':65536}

    detector_to_x_axis = {
        'mar':'1.0 0.0 0.0',
        'marccd':'1.0 0.0 0.0',        
        'raxis':'1.0 0.0 0.0',
        'adsc':'1.0 0.0 0.0'}

    detector_to_y_axis = {
        'mar':'0.0 1.0 0.0',
        'marccd':'0.0 1.0 0.0',        
        'raxis':'0.0 -1.0 0.0',
        'adsc':'0.0 1.0 0.0'}

    detector_class_is_square = {
        'adsc q4':True,
        'adsc q4 2x2 binned':True,
        'adsc q210':True,
        'adsc q210 2x2 binned':True,
        'adsc q315':True,
        'adsc q315 2x2 binned':True,
        'mar 345':False,
        'mar 300':True,
        'mar 225':True,
        'mar 165':False,
        'raxis IV':True}

    detector_to_rotation_axis = {
        'mar':'1.0 0.0 0.0',
        'marccd':'1.0 0.0 0.0',        
        'raxis':'0.0 1.0 0.0',
        'adsc':'1.0 0.0 0.0'}

    # --------- end mapping tables ---------

    width, height = tuple(map(int, header['size']))
    qx, qy = tuple(header['pixel'])

    detector = header['detector']
    detector_class = header['detector_class']

    result = []

    result.append('DETECTOR %s MINIMUM_VALID_PIXEL_VALUE=%d OVERLOAD=%d' % \
                  (detector_to_detector[detector], 0,
                   detector_to_overload[detector]))

    result.append('DIRECTION_OF_DETECTOR_X-AXIS=%s' % \
                  detector_to_x_axis[detector])

    result.append('DIRECTION_OF_DETECTOR_Y-AXIS=%s' % \
                  detector_to_y_axis[detector])

    if detector_class_is_square[detector_class]:
        result.append('TRUSTED_REGION=0.0 1.41')
    else:
        result.append('TRUSTED_REGION=0.0 0.99')

    result.append('NX=%d NY=%d QX=%6.4f QY=%6.4f' % \
                  (width, height, qx, qy))

    result.append('ORGX=%d ORGX=%d' % \
                  (width / 2, height / 2))

    result.append('ROTATION_AXIS= %s' % \
                  detector_to_rotation_axis[detector])

    result.append('INCIDENT_BEAM_DIRECTION=0.0 0.0 1.0')

    return result


if __name__ == '__main__':
    from Wrappers.XIA.Printheader import Printheader

    ph = Printheader()

    directory = os.path.join(os.environ['XIA2_ROOT'],
                             'Data', 'Test', 'Images')

    ph.set_image(os.path.join(directory, '12287_1_E1_001.img'))
    for record in header_to_xds(ph.readheader()):
        print record
