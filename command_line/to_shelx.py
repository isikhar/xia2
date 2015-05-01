from __future__ import division

def to_shelx(hklin, prefix):
  '''Read hklin (unmerged reflection file) and generate SHELXT input file
  and HKL file'''

  from iotbx.reflection_file_reader import any_reflection_file
  from iotbx.shelx import writer
  from cctbx.xray.structure import structure

  reader = any_reflection_file(hklin)
  intensities = [ma for ma in reader.as_miller_arrays(merge_equivalents=False)
                 if ma.info().labels == ['I', 'SIGI']][0]
  with open('%s.hkl' % prefix, 'wb') as f:
    intensities.export_as_shelx_hklf(f)

  crystal_symm = intensities.crystal_symmetry()
  xray_structure = structure(crystal_symmetry=crystal_symm)
  open('%s.ins' % prefix, 'w').write(''.join(writer.generator(xray_structure,
                            full_matrix_least_squares_cycles=0,
                            title=prefix)))

if __name__ == '__main__':
  import sys
  to_shelx(sys.argv[1], sys.argv[2])