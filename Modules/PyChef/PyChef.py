#!/usr/bin/env python
# PyChef.py
# 
#   Copyright (C) 2009 Diamond Light Source, Graeme Winter
#
#   This code is distributed under the BSD license, a copy of which is 
#   included in the root directory of this package.
# 
# A reimplementation of the FORTRAN program CHEF (Winter, unpublished work)
# into Python, using the CCTBX library. The idea is to analyse scaled 
# intensity measurements as a function of cumulative dose, to assess the
# impact of radiation damage.
#

import sys
import math
import os
import time

from PyChefHelpers import get_mtz_column_list, compute_unique_reflections

from iotbx import mtz

class PyChef:
    '''The main PyChef class.'''

    def __init__(self):

        self._base_column = 'BATCH'

        self._hklin_list = []

        self._reflections = { }
        self._unit_cells = { }
        self._space_groups = { }

        # assuming that we will be using BATCH by default...

        self._range_min = None
        self._range_max = None
        self._range_width = 1
        
        self._resolution_high = None
        self._resolution_low = None

        self._resolution_bins = 8

        self._anomalous = False

        self.banner()

        return

    def banner(self):
        version = '1.0'
        user = os.environ.get('USER', '')
        now = time.asctime()
        
        print '#' * 60
        print '#' * 60
        print '#' * 60
        print '### PyCHEF                                           %s ###' % \
              version
        print '#' * 60
        print 'User: %s                  Run at: %s' % (user, now)

        return
        
    def set_base_column(self, base_column):
        '''Set the baseline for analysis: note well that this should
        be called before add_hklin, so that add_hklin can check that
        this column is present.'''

        self._base_column = base_column

        return

    def add_hklin(self, hklin):
        '''Add a reflection file to the list for analysis... '''

        columns = get_mtz_column_list(hklin)

        assert(self._base_column in columns)

        self._hklin_list.append(hklin)

        return

    def set_range(self, range_min, range_max, range_width):
        '''Set the range of e.g. dose to consider for analysis, with
        binning width set.'''

        assert(range_max > range_min)
        assert(range_max - range_min > range_width)

        self._range_min = range_min
        self._range_max = range_max
        self._range_width = range_width

        return

    def set_resolution(self, resolution_high, resolution_low = None):
        '''Set the resolution range for analysis.'''

        self._resolution_high = resolution_high

        if resolution_low:
            assert(resolution_low > resolution_high)
            self._resolution_low = resolution_low

        return

    def set_anomalous(self, anomalous):
        '''Set the separation of anomalous pairs on or off.'''

        self._anomalous = anomalous
        return

    def init(self):
        '''Initialise the program - this will read all of the reflections
        and so on into memory and set up things like the unit cell objects.'''

        symmetry = None

        overall_dmin = None
        overall_dmax = None

        overall_range_min = None
        overall_range_max = None

        for hklin in self._hklin_list:
            
            mtz_obj = mtz.object(hklin)

            mi = mtz_obj.extract_miller_indices()
            dmax, dmin = mtz_obj.max_min_resolution()

            if overall_dmin is None:
                overall_dmin = dmin
            else:
                if dmin > overall_dmin:
                    overall_dmin = dmin

            if overall_dmax is None:
                overall_dmax = dmax
            else:
                if dmax < overall_dmax:
                    overall_dmax = dmax

            crystal_name = None
            dataset_name = None
            nref = 0
            uc = None

            # chef does not care about systematic absences from e.g.
            # screw axes => patterson group not space group. No,
            # patterson group is always centric?!
            
            sg = mtz_obj.space_group()

            # .build_derived_patterson_group()

            if not symmetry:
                symmetry = sg
            else:
                assert(symmetry == sg)

            # now have a rummage through to get the columns out that I want
                
            base_column = None
            misym_column = None
            i_column = None
            sigi_column = None

            for crystal in mtz_obj.crystals():

                for dataset in crystal.datasets():
                    if dataset.name() != 'HKL_base':
                        dataset_name = dataset.name()

                if crystal.name() != 'HKL_base':
                    crystal_name = crystal.name()
                
                uc = crystal.unit_cell()

                for dataset in crystal.datasets():

                    for column in dataset.columns():

                        if column.label() == self._base_column:
                            base_column = column
                        if column.label() == 'M_ISYM':
                            misym_column = column
                        if column.label() == 'I':
                            i_column = column
                        if column.label() == 'SIGI':
                            sigi_column = column

            assert(base_column != None)
            assert(misym_column != None)
            assert(i_column != None)
            assert(sigi_column != None)

            print 'Reading in data from %s/%s' % (crystal_name, dataset_name)
            print 'Cell: %6.2f %6.2f %6.2f %6.2f %6.2f %6.2f' % \
                  tuple(uc.parameters())
            print 'Spacegroup: %s' % sg.type(
                ).universal_hermann_mauguin_symbol()
            print 'Using: %s/%s/%s' % \
                  (i_column.label(), sigi_column.label(), base_column.label())

            base_values = base_column.extract_values(
                not_a_number_substitute = 0.0)

            min_base = min(base_values)
            max_base = max(base_values)

            if overall_range_min == None:
                overall_range_min = min_base
            else:
                if min_base < overall_range_min:
                    overall_range_min = min_base

            if overall_range_max == None:
                overall_range_max = max_base
            else:
                if max_base > overall_range_max:
                    overall_range_max = max_base

            misym_values = misym_column.extract_values(
                not_a_number_substitute = 0.0)

            i_values = i_column.extract_values(
                not_a_number_substitute = 0.0)
            i_values_valid = i_column.selection_valid()

            sigi_values = sigi_column.extract_values(
                not_a_number_substitute = 0.0)
            sigi_values_valid = sigi_column.selection_valid()

            reflections = { }

            for j in range(mi.size()):

                if not i_values_valid[j]:
                    continue
                
                if not sigi_values_valid[j]:
                    continue
                
                h, k, l = mi[j]
                base = base_values[j]
                misym = misym_values[j]
                i = i_values[j]
                sigi = sigi_values[j]

                # test whether this is within the range of interest

                if self._range_min != None:
                    if base < self._range_min:
                        continue

                if self._range_max != None:
                    if base > self._range_max:
                        continue

                if self._resolution_high:
                    if uc.d([h, k, l]) < self._resolution_high:
                        continue
                
                if self._resolution_low:
                    if uc.d([h, k, l]) > self._resolution_low:
                        continue

                if self._anomalous:
                    pm = int(round(misym)) % 2
                else:
                    pm = 0

                if not (h, k, l) in reflections:
                    reflections[(h, k, l)] = []

                reflections[(h, k, l)].append((pm, base, i, sigi))

            # ok, copy the reflections to the class for future analysis

            self._reflections[(crystal_name, dataset_name)] = reflections
            self._unit_cells[(crystal_name, dataset_name)] = uc
            self._space_groups[(crystal_name, dataset_name)] = sg

        if not self._resolution_low:
            print 'Assigning low resolution limit: %.2f' % overall_dmax
            self._resolution_low = overall_dmax

        if not self._resolution_high:
            print 'Assigning high resolution limit: %.2f' % overall_dmin
            self._resolution_high = overall_dmin

        if not self._range_min:
            print 'Assigning baseline minimum: %.2f' % \
                  (overall_range_min - self._range_width)
            self._range_min = overall_range_min - self._range_width

        if not self._range_max:
            print 'Assigning baseline maximum: %.2f' % \
                  overall_range_max
            self._range_max = overall_range_max

        # if > 1 data set assume that this is anomalous data...

        if len(self._reflections) > 1:
            print 'More than one data set: assume anomalous'
            self._anomalous = True

        # FIXME add warning if measurements don't reach the edge...

        return
        
    def print_completeness_vs_dose(self):
        '''Print the completeness vs. dose for each input reflection file.
        This will need to read the MTZ file, get the dataset cell constants
        and space group, compute the expected number of reflections, then
        as a function of dose compute what fraction of these are measured.
        For native data this is going to simply write out:

        dose, fraction

        but for MAD data it will need to print out:

        dose, fractionI+, fractionI-, fractionI, fractionI+andI-

        would be nice to have this described a little tidier.'''

        for crystal_name, dataset_name in self._reflections:

            reflections = self._reflections[(crystal_name, dataset_name)]
            uc = self._unit_cells[(crystal_name, dataset_name)]
            sg = self._space_groups[(crystal_name, dataset_name)]

            nref = len(compute_unique_reflections(uc, sg, self._anomalous,
                                                  self._resolution_high,
                                                  self._resolution_low))
            
            nref_n = len(compute_unique_reflections(uc, sg, False,
                                                    self._resolution_high,
                                                    self._resolution_low))

            print 'Cumulative completeness analysis for %s/%s' % \
                  (crystal_name, dataset_name)
            print 'Expecting %d reflections' % nref
            
            # Right, in here I need to get the lowest dose for a given
            # h, k, l and then add this reflection for completeness to all
            # high dose bins, as it is measured already. So, if it is
            #
            # centric and anomalous, add to I+ and I-
            # centric and not anomalous, add to I
            # acentric and anomalous, add to I+ or I-
            # acentric and not anomalous, add to I
            #
            # To do this the best thing to do is to read through all of the
            # reflections and keep a dictionary of the lowest dose at which
            # a given reflection was recorded. Then iterate through this
            # list to see how many we have as a function of dose...
            #
            # Ok, so after trying to implement this cleanly I think that the 
            # only way to do this is to actually read all of the reflections
            # in and store them in e.g. a dictionary. Could be expensive
            # for large data sets, but worry about that ... later. Can at
            # least store this in-memory representation. Accordingly will also
            # need to read in the 'I' column...

            # this will be a dictionary indexed by the Miller indices and
            # containing anomalous flag (1: I+, 0:I- or native) baseline
            # intensity values and the error estimate.. 
            
            # now construct the completeness tables for I or I+ & I-,
            # then populate from this list of lowest doses...

            if self._anomalous:

                print '$TABLE : Completeness vs. %s, %s %s:' % \
                      (self._base_column, crystal_name, dataset_name)
                print '$GRAPHS: Completeness:N:1,2,3,4,5: $$'
                print '%8s %5s %5s %5s %5s $$ $$' % \
                      (self._base_column, 'I+', 'I-', 'I', 'dI')

                iplus_count = []
                iminus_count = []
                ieither_count = []
                iboth_count = []

                nsteps = 1 + int(
                    (self._range_max - self._range_min) / self._range_width)

                for j in range(nsteps):
                    iplus_count.append(0)
                    iminus_count.append(0)
                    ieither_count.append(0)
                    iboth_count.append(0)

                for h, k, l in reflections:
                    base_min_iplus = self._range_max + self._range_width
                    base_min_iminus = self._range_max + self._range_width

                    for pm, base, i, sigi in reflections[(h, k, l)]:
                        if sg.is_centric((h, k, l)):
                            if base < base_min_iplus:
                                base_min_iplus = base
                            if base < base_min_iminus:
                                base_min_iminus = base
                        elif pm:
                            if base < base_min_iplus:
                                base_min_iplus = base
                        else:
                            if base < base_min_iminus:
                                base_min_iminus = base

                    start_iplus = int((base_min_iplus - self._range_min)
                                      / self._range_width)

                    start_iminus = int((base_min_iminus - self._range_min)
                                      / self._range_width)

                    if start_iplus < nsteps:
                        iplus_count[start_iplus] += 1
                    if start_iminus < nsteps:
                        iminus_count[start_iminus] += 1
                    if min(start_iplus, start_iminus) < nsteps:
                        ieither_count[min(start_iplus, start_iminus)] += 1
                    if max(start_iplus, start_iminus) < nsteps:
                        iboth_count[max(start_iplus, start_iminus)] += 1

                # now sum up

                for j in range(1, nsteps):
                    iplus_count[j] += iplus_count[j - 1]
                    iminus_count[j] += iminus_count[j - 1]
                    ieither_count[j] += ieither_count[j - 1]
                    iboth_count[j] += iboth_count[j - 1]

                for j in range(nsteps):
                    iplus = iplus_count[j] / float(nref_n)
                    iminus = iminus_count[j] / float(nref_n)
                    ieither = ieither_count[j] / float(nref_n)
                    iboth = iboth_count[j] / float(nref_n)
                    
                    print '%8.1f %5.3f %5.3f %5.3f %5.3f' % \
                          (self._range_min + j * self._range_width,
                           iplus, iminus, ieither, iboth)

                print '$$'

            else:

                print '$TABLE : Completeness vs. %s, %s/%s:' % \
                      (self._base_column, crystal_name, dataset_name)
                print '$GRAPHS: Completeness:N:1, 2: $$'
                print '%8s %5s $$ $$' % (self._base_column, 'I')

                i_count = []

                nsteps = 1 + int(
                    (self._range_max - self._range_min) / self._range_width)

                for j in range(nsteps):
                    i_count.append(0)

                for h, k, l in reflections:
                    base_min = self._range_max + self._range_width

                    for pm, base, i, sigi in reflections[(h, k, l)]:
                        if base < base_min:
                            base_min = base

                    start = int((base_min - self._range_min)
                                / self._range_width)

                    # for j in range(start, nsteps):
                    i_count[start] += 1

                for j in range(1, nsteps):
                    i_count[j] += i_count[j - 1]

                for j in range(nsteps):
                    i = i_count[j] / float(nref)
                    
                    print '%8.1f %5.3f' % \
                          (self._range_min + j * self._range_width, i)

                print '$$'

        return

    def scp(self):
        '''Perform the scp = rcp / ercp calculation as a function of
        assumulated dose across a number of resolution bins, from
        measurements already cached in memory.'''

        rcp_top = { }
        rcp_bottom = { }
        isigma = { }
        count = { }

        if self._resolution_low:
            smin = 1.0 / (self._resolution_low * self._resolution_low)
        else:
            smin = 0.0

        smax = 1.0 / (self._resolution_high * self._resolution_high)

        nsteps = 1 + int(
            (self._range_max - self._range_min) / self._range_width)

        # lay out the storage 

        for j in range(self._resolution_bins + 1):

            rcp_top[j] = []
            rcp_bottom[j] = []
            isigma[j] = []
            count[j] = []
            
            for k in range(nsteps):
                rcp_top[j].append(0.0)
                rcp_bottom[j].append(0.0)
                isigma[j].append(0.0)
                count[j].append(0)

        # then populate

        for xname, dname in sorted(self._reflections):

            print 'Accumulating from %s %s' % (xname, dname)
            
            for h, k, l in self._reflections[(xname, dname)]:

                d = self._unit_cells[(xname, dname)].d([h, k, l])

                s = 1.0 / (d * d)

                bin = int(self._resolution_bins * (s - smin) / (smax - smin))
                
                observations = self._reflections[(xname, dname)][(h, k, l)]

                iplus = []
                iminus = []

                for pm, base, i, sigi in observations:
                    if pm:
                        iplus.append((base, i, sigi))
                    else:
                        iminus.append((base, i, sigi))

                # compute contributions

                for n, (base, i, sigi) in enumerate(iplus):

                    for _base, _i, _sigi in iplus[n + 1:]:
                        start = int((max(base, _base) - self._range_min) /
                                    self._range_width)

                        ra = math.fabs(i - _i)
                        rb = 0.5 * (i + _i)

                        rcp_top[bin][start] += ra
                        rcp_bottom[bin][start] += rb

                        isigma[bin][start] += (i / sigi) + (_i / _sigi)
                        count[bin][start] += 2

                for n, (base, i, sigi) in enumerate(iminus):

                    for _base, _i, _sigi in iminus[n + 1:]:
                        start = int((max(base, _base) - self._range_min) /
                                    self._range_width)

                        ra = math.fabs(i - _i)
                        rb = 0.5 * (i + _i)

                        rcp_top[bin][start] += ra
                        rcp_bottom[bin][start] += rb

                        isigma[bin][start] += (i / sigi) + (_i / _sigi)
                        count[bin][start] += 2

        # now accumulate as a funtion of time...

        for k in range(self._resolution_bins):
            for j in range(1, nsteps):
                rcp_top[k][j] += rcp_top[k][j - 1]
                rcp_bottom[k][j] += rcp_bottom[k][j - 1]
                isigma[k][j] += isigma[k][j - 1]
                count[k][j] += count[k][j - 1]

        # now digest the results - as a function of dose and resolution...

        print '$TABLE : Cumulative radiation damage analysis:'
        print '$GRAPHS: Scp(d):N:1,%d: $$' % (self._resolution_bins + 2)

        columns = ''
        for j in range(self._resolution_bins):
            columns += ' S%d' % j
        
        print '%s %s Scp(d) $$ $$' % (self._base_column, columns)
        format = '%8.1f %5.3f'
        for k in range(self._resolution_bins):
            format += ' %5.3f'

        for j in range(nsteps):
            base = j * self._range_width + self._range_min
            values = [base]

            for k in range(self._resolution_bins):

                if rcp_bottom[k][j] and count[k][j] > 100:
                    rcp = rcp_top[k][j] / rcp_bottom[k][j]
                    isig = isigma[k][j] / count[k][j]
                    scp = rcp / (1.1284 / isig)
                else:
                    scp = 0.0
                    rcp = 0.0
                    isig = 0.0

                values.append(scp)

            values.append((sum(values[1:]) / self._resolution_bins))

            print format % tuple(values)

        print '$$'

        return
    
                        
