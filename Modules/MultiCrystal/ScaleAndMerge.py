#!/usr/bin/env dials.python
from __future__ import absolute_import, division, print_function

import copy
import logging
import math
import os
import py

from libtbx import Auto
import iotbx.phil
from cctbx import crystal
from cctbx import sgtbx
from dxtbx.serialize import dump, load
from dxtbx.model import ExperimentList

from dials.array_family import flex
from dials.command_line.unit_cell_histogram import plot_uc_histograms

from dials.util import log

from xia2.lib.bits import auto_logfiler
from xia2.Handlers.Phil import PhilIndex
from xia2.Handlers.Environment import get_number_cpus
from xia2.Modules.MultiCrystal import multi_crystal_analysis
from xia2.Wrappers.Dials.Cosym import DialsCosym
from xia2.Wrappers.Dials.Refine import Refine
from xia2.Wrappers.Dials.Scale import DialsScale
from xia2.Wrappers.Dials.Symmetry import DialsSymmetry
from xia2.Wrappers.Dials.TwoThetaRefine import TwoThetaRefine


logger = logging.getLogger(__name__)


# The phil scope
phil_scope = iotbx.phil.parse('''
unit_cell_clustering {
  threshold = 5000
    .type = float(value_min=0)
    .help = 'Threshold value for the clustering'
  log = False
    .type = bool
    .help = 'Display the dendrogram with a log scale'
}

scaling
{
  #intensities = summation profile *combine
    #.type = choice
  surface_tie = 0.001
    .type = float
    .short_caption = "Surface tie"
  surface_link = True
    .type = bool
    .short_caption = "Surface link"
  rotation.spacing = 2
    .type = int
    .expert_level = 2
    .short_caption = "Interval (in degrees) between scale factors on rotation axis"
  brotation.spacing = None
    .type = int
    .expert_level = 2
    .short_caption = "Interval (in degrees) between B-factors on rotation axis"
  secondary {
    frame = camera *crystal
      .type = choice
      .help = "Whether to do the secondary beam correction in the camera spindle"
              "frame or the crystal frame"
    lmax = 0
      .type = int
      .expert_level = 2
      .short_caption = "Number of spherical harmonics for absorption correction"
  }
  dials {
    model = physical array KB auto
      .type = choice
    outlier_rejection = simple *standard
      .type = choice
    Isigma_range = 2.0,100000
      .type = floats(size=2)
    min_partiality = None
      .type = float(value_min=0, value_max=1)
    partiality_cutoff = None
      .type = float(value_min=0, value_max=1)
  }
}

symmetry {
  resolve_indexing_ambiguity = True
    .type = bool
  cosym {
    include scope dials.algorithms.symmetry.cosym.phil_scope
  }
  le_page_max_delta = 5
    .type = float(value_min=0)
  space_group = None
    .type = space_group
}

resolution
  .short_caption = "Resolution"
{
  d_max = None
    .type = float(value_min=0.0)
    .help = "Low resolution cutoff."
    .short_caption = "Low resolution cutoff"
  d_min = None
    .type = float(value_min=0.0)
    .help = "High resolution cutoff."
    .short_caption = "High resolution cutoff"
  include scope dials.util.Resolutionizer.phil_str
}

multi_crystal_analysis {
  include scope xia2.Modules.MultiCrystal.master_phil_scope
}

min_completeness = None
  .type = float(value_min=0, value_max=1)
min_multiplicity = None
  .type = float(value_min=0)
max_clusters = None
  .type = int(value_min=1)

identifiers = None
  .type = strings

dose = None
  .type = ints(size=2, value_min=0)

nproc = Auto
  .type = int(value_min=1)
  .help = "The number of processors to use"
  .expert_level = 0
remove_profile_fitting_failures = True
  .type = bool

''', process_includes=True)

# override default parameters
phil_scope = phil_scope.fetch(source=iotbx.phil.parse(
  """\
resolution {
  cc_half_method = sigma_tau
  cc_half_fit = tanh
  cc_half = 0.3
  isigma = None
  misigma = None
}
"""))


class DataManager(object):
  def __init__(self, experiments, reflections):
    self._input_experiments = experiments
    self._input_reflections = reflections

    self._experiments = copy.deepcopy(experiments)
    self._reflections = copy.deepcopy(reflections)

    self._set_batches()

  def _set_batches(self):
    max_batches = max(e.scan.get_image_range()[1] for e in self._experiments)
    max_batches += 10 # allow some head room

    n = int(math.ceil(math.log10(max_batches)))

    for i, expt in enumerate(self._experiments):
      expt.scan.set_batch_offset(i * 10**n)
      logger.debug("%s %s" % (expt.scan.get_batch_offset(), expt.scan.get_batch_range()))

  @property
  def experiments(self):
    return self._experiments

  @experiments.setter
  def experiments(self, experiments):
    self._experiments = experiments

  @property
  def reflections(self):
    return self._reflections

  @reflections.setter
  def reflections(self, reflections):
    self._reflections = reflections

  def select(self, experiment_identifiers):
    self._experiments = ExperimentList(
      [expt for expt in self._experiments
       if expt.identifier in experiment_identifiers])
    self.reflections = self.reflections.select_on_experiment_identifiers(
      experiment_identifiers)
    self.reflections.reset_ids()
    self.reflections.assert_experiment_identifiers_are_consistent(
      self.experiments)

  def filter_dose(self, dose_min, dose_max):
    from dials.command_line.slice_sweep import slice_experiments, slice_reflections
    image_range = [
      (max(dose_min, expt.scan.get_image_range()[0]),
       min(dose_max, expt.scan.get_image_range()[1]))
      for expt in self._experiments]
    n_refl_before = self._reflections.size()
    self._experiments = slice_experiments(self._experiments, image_range)
    flex.min_max_mean_double(self._reflections['xyzobs.px.value'].parts()[2]).show()
    self._reflections = slice_reflections(self._reflections, image_range)
    flex.min_max_mean_double(self._reflections['xyzobs.px.value'].parts()[2]).show()
    logger.info('%i reflections out of %i remaining after filtering for dose' %
                (self._reflections.size(), n_refl_before))

  def reflections_as_miller_arrays(self, intensity_key='intensity.sum.value', return_batches=False):
    from cctbx import crystal, miller
    variance_key = intensity_key.replace('.value', '.variance')
    assert intensity_key in self._reflections, intensity_key
    assert variance_key in self._reflections, variance_key

    miller_arrays = []
    for expt in self._experiments:
      crystal_symmetry = crystal.symmetry(
        unit_cell=expt.crystal.get_unit_cell(),
        space_group=expt.crystal.get_space_group())
      refl = self._reflections.select(
        self._reflections.get_flags(self._reflections.flags.integrated_sum))
      refl = refl.select_on_experiment_identifiers([expt.identifier])
      assert refl.size() > 0, expt.identifier

      from dials.util.filter_reflections import filter_reflection_table
      if intensity_key == 'intensity.scale.value':
        intensity_choice = ['scale']
        intensity_to_use = 'scale'
      elif intensity_key == 'intensity.prf.value':
        intensity_choice.append('profile')
        intensity_to_use = 'prf'
      else:
        intensity_choice = ['sum']
        intensity_to_use = 'sum'

      partiality_threshold = 0.99
      refl = filter_reflection_table(refl, intensity_choice, min_isigi=-5,
        filter_ice_rings=False, combine_partials=True,
        partiality_threshold=partiality_threshold)
      assert refl.size() > 0
      data = refl['intensity.'+intensity_to_use+'.value']
      variances = refl['intensity.'+intensity_to_use+'.variance']

      if return_batches:
        batch_offset = expt.scan.get_batch_offset()
        zdet = refl['xyzobs.px.value'].parts()[2]
        batches = flex.floor(zdet).iround() + 1 + batch_offset

      miller_indices = refl['miller_index']
      assert variances.all_gt(0)
      sigmas = flex.sqrt(variances)

      miller_set = miller.set(crystal_symmetry, miller_indices, anomalous_flag=False)
      intensities = miller.array(miller_set, data=data, sigmas=sigmas)
      intensities.set_observation_type_xray_intensity()
      intensities.set_info(miller.array_info(
        source='DIALS', source_type='pickle'))
      if return_batches:
        batches = miller.array(miller_set, data=batches).set_info(
          intensities.info())
        miller_arrays.append([intensities, batches])
      else:
        miller_arrays.append(intensities)
    return miller_arrays

  def reindex(self, cb_op, space_group=None):
    logger.info('Reindexing: %s' % cb_op)
    self._reflections['miller_index'] = cb_op.apply(self._reflections['miller_index'])

    for expt in self._experiments:
      cryst_reindexed = expt.crystal.change_basis(cb_op)
      if space_group is not None:
        cryst_reindexed.set_space_group(space_group)
      expt.crystal.update(cryst_reindexed)

  def export_reflections(self, filename):
    self._reflections.as_pickle(filename)
    return filename

  def export_experiments(self, filename):
    dump.experiment_list(self._experiments, filename)
    return filename


class MultiCrystalScale(object):
  def __init__(self, experiments, reflections, params):

    self._data_manager = DataManager(experiments, reflections)

    self._params = params

    if self._params.nproc is Auto:
      self._params.nproc = get_number_cpus()
    PhilIndex.params.xia2.settings.multiprocessing.nproc = self._params.nproc

    if self._params.identifiers is not None:
      self._data_manager.select(self._params.identifiers)
    if self._params.dose is not None:
      self._data_manager.filter_dose(*self._params.dose)

    if params.remove_profile_fitting_failures:
      reflections = self._data_manager.reflections
      profile_fitted_mask = reflections.get_flags(reflections.flags.integrated_prf)
      keep_expts = []
      for i, expt in enumerate(self._data_manager.experiments):
        if reflections.select(
            profile_fitted_mask).select_on_experiment_identifiers(
              [expt.identifier]).size():
          keep_expts.append(expt.identifier)
      if len(keep_expts):
        logger.info('Selecting %i experiments with profile-fitted reflections'
                     % len(keep_expts))
        self._data_manager.select(keep_expts)

    reflections = self._data_manager.reflections
    used_in_refinement_mask = reflections.get_flags(reflections.flags.used_in_refinement)
    keep_expts = []
    for i, expt in enumerate(self._data_manager.experiments):
      if reflections.select(
          used_in_refinement_mask).select_on_experiment_identifiers(
            [expt.identifier]).size():
        keep_expts.append(expt.identifier)
      else:
        logger.info(
          'Removing experiment %s (no refined reflections remaining)'
          % expt.identifier)
    if len(keep_expts):
      logger.info('Selecting %i experiments with refined reflections'
                   % len(keep_expts))
      self._data_manager.select(keep_expts)

    experiments = self._data_manager.experiments
    reflections = self._data_manager.reflections

    self.unit_cell_clustering(plot_name='cluster_unit_cell_p1.png')

    self.unit_cell_histogram(plot_name='unit_cell_histogram.png')

    if self._params.symmetry.resolve_indexing_ambiguity:
      self.cosym()

    self._scaled = Scale(self._data_manager, self._params)

    self.unit_cell_clustering(plot_name='cluster_unit_cell_sg.png')

    self._data_manager.export_experiments('experiments_final.json')
    self._data_manager.export_reflections('reflections_final.pickle')

    scaled_unmerged_mtz = py.path.local(self._scaled.scaled_unmerged_mtz)
    scaled_unmerged_mtz.copy(py.path.local('scaled_unmerged.mtz'))
    scaled_mtz = py.path.local(self._scaled.scaled_mtz)
    scaled_mtz.copy(py.path.local('scaled.mtz'))

    self.report()

    min_completeness = self._params.min_completeness
    min_multiplicity = self._params.min_multiplicity
    max_clusters = self._params.max_clusters
    if ((max_clusters is not None and max_clusters > 1)
        or min_completeness is not None or min_multiplicity is not None):
      self._data_manager_original = self._data_manager
      cwd = os.path.abspath(os.getcwd())
      n_processed = 0
      for cluster in reversed(self._cos_angle_clusters):
        if max_clusters is not None and n_processed == max_clusters:
          break
        if min_completeness is not None and cluster.completeness < min_completeness:
          continue
        if min_multiplicity is not None and cluster.multiplicity < min_multiplicity:
          continue
        if len(cluster.labels) == len(self._data_manager_original.experiments):
          continue
        n_processed += 1

        logger.info('Scaling cos angle cluster %i:' % cluster.cluster_id)
        logger.info(cluster)
        cluster_dir = 'cos_angle_cluster_%i' % cluster.cluster_id
        os.mkdir(cluster_dir)
        os.chdir(cluster_dir)
        data_manager = copy.deepcopy(self._data_manager_original)
        data_manager.select(cluster.labels)
        scaled = Scale(data_manager, self._params)
        os.chdir(cwd)

  @staticmethod
  def stereographic_projections(experiments_filename):
    from xia2.Wrappers.Dials.StereographicProjection import StereographicProjection
    sp_json_files = {}
    for hkl in ((1,0,0), (0,1,0), (0,0,1)):
      sp = StereographicProjection()
      auto_logfiler(sp)
      sp.add_experiments(experiments_filename)
      sp.set_hkl(hkl)
      sp.run()
      sp_json_files[hkl] = sp.get_json_filename()
    return sp_json_files

  def unit_cell_clustering(self, plot_name=None):
    crystal_symmetries = []
    for expt in self._data_manager.experiments:
      crystal_symmetry = expt.crystal.get_crystal_symmetry(
        assert_is_compatible_unit_cell=False)
      crystal_symmetries.append(crystal_symmetry.niggli_cell())
    lattice_ids = [expt.identifier for expt in self._data_manager.experiments]
    from xfel.clustering.cluster import Cluster
    from xfel.clustering.cluster_groups import unit_cell_info
    ucs = Cluster.from_crystal_symmetries(crystal_symmetries, lattice_ids=lattice_ids)
    if plot_name is not None:
      from matplotlib import pyplot as plt
      plt.figure("Andrews-Bernstein distance dendogram", figsize=(12, 8))
      ax = plt.gca()
    else:
      ax = None
    clusters, _ = ucs.ab_cluster(
      self._params.unit_cell_clustering.threshold,
      log=self._params.unit_cell_clustering.log,
      write_file_lists=False,
      schnell=False,
      doplot=(plot_name is not None),
      ax=ax
    )
    if plot_name is not None:
      plt.tight_layout()
      plt.savefig(plot_name)
      plt.clf()
    logger.info(unit_cell_info(clusters))
    largest_cluster = None
    largest_cluster_lattice_ids = None
    for cluster in clusters:
      cluster_lattice_ids = [m.lattice_id for m in cluster.members]
      if largest_cluster_lattice_ids is None:
        largest_cluster_lattice_ids = cluster_lattice_ids
      elif len(cluster_lattice_ids) > len(largest_cluster_lattice_ids):
        largest_cluster_lattice_ids = cluster_lattice_ids

    if len(largest_cluster_lattice_ids) < len(crystal_symmetries):
      logger.info(
        'Selecting subset of data sets for subsequent analysis: %s' %str(largest_cluster_lattice_ids))
      self._data_manager.select(largest_cluster_lattice_ids)
    else:
      logger.info('Using all data sets for subsequent analysis')

  def unit_cell_histogram(self, plot_name=None):

    uc_params = [flex.double() for i in range(6)]
    for expt in self._data_manager.experiments:
      uc = expt.crystal.get_unit_cell()
      for i in range(6):
        uc_params[i].append(uc.parameters()[i])

    iqr_ratio = 1.5
    outliers = flex.bool(uc_params[0].size(), False)
    for p in uc_params:
      from scitbx.math import five_number_summary
      min_x, q1_x, med_x, q3_x, max_x = five_number_summary(p)
      logger.info(
        'Five number summary: min %.2f, q1 %.2f, med %.2f, q3 %.2f, max %.2f'
        % (min_x, q1_x, med_x, q3_x, max_x))
      iqr_x = q3_x - q1_x
      if iqr_x < 1e-6:
        continue
      cut_x = iqr_ratio * iqr_x
      outliers.set_selected(p > q3_x + cut_x, True)
      outliers.set_selected(p < q1_x - cut_x, True)
    logger.info('Identified %i unit cell outliers' % outliers.count(True))

    plot_uc_histograms(uc_params, outliers)

  def cosym(self):
    logger.debug('Running cosym analysis')
    cosym = DialsCosym()
    auto_logfiler(cosym)

    experiments_filename = self._data_manager.export_experiments(
      'tmp_experiments.json')
    reflections_filename = self._data_manager.export_reflections(
      'tmp_reflections.pickle')
    cosym.add_experiments_json(experiments_filename)
    cosym.add_reflections_pickle(reflections_filename)
    if self._params.symmetry.space_group is not None:
      cosym.set_space_group(self._params.symmetry.space_group.group())
    cosym.run()

    self._experiments_filename = cosym.get_reindexed_experiments()
    self._reflections_filename = cosym.get_reindexed_reflections()
    self._data_manager.experiments = load.experiment_list(
      self._experiments_filename, check_format=False)
    self._data_manager.reflections = flex.reflection_table.from_pickle(
      self._reflections_filename)
    return

  def report(self):
    from xia2.command_line.multi_crystal_analysis import multi_crystal_analysis
    from xia2.command_line.multi_crystal_analysis import phil_scope as mca_phil
    params = mca_phil.extract()
    params.prefix = 'multi-crystal'
    params.title = 'Multi crystal report'
    mca = multi_crystal_analysis(
      self._data_manager.experiments,
      self._data_manager.reflections,
      params
    )
    self._cos_angle_clusters = mca._cluster_analysis.cos_angle_clusters


class Scale(object):
  def __init__(self, data_manager, params):
    self._data_manager = data_manager
    self._params = params

    self.decide_space_group()

    self.two_theta_refine()

    #self.unit_cell_clustering(plot_name='cluster_unit_cell_sg.png')

    self.scale()

    d_min, reason = self.estimate_resolution_limit()

    logger.info('Resolution limit: %.2f (%s)' % (d_min, reason))

    self.scale(d_min=d_min)

  def decide_space_group(self):

    if self._params.symmetry.space_group is not None:
      # reindex to correct bravais setting
      cb_op = sgtbx.change_of_basis_op()
      self._data_manager.reindex(
        cb_op=cb_op, space_group=self._params.symmetry.space_group.group())
      self._experiments_filename = 'experiments.json'
      self._reflections_filename = 'reflections.pickle'
      self._data_manager.export_experiments(self._experiments_filename)
      self._data_manager.export_reflections(self._reflections_filename)
      return

    logger.debug('Deciding space group with dials.symmetry')
    symmetry = DialsSymmetry()
    auto_logfiler(symmetry)

    self._experiments_filename = '%i_experiments_reindexed.json' % symmetry.get_xpid()
    self._reflections_filename = '%i_reflections_reindexed.pickle' % symmetry.get_xpid()

    experiments_filename = 'tmp_experiments.json'
    reflections_filename = 'tmp_reflections.pickle'
    self._data_manager.export_experiments(experiments_filename)
    self._data_manager.export_reflections(reflections_filename)

    symmetry.set_experiments_filename(experiments_filename)
    symmetry.set_reflections_filename(reflections_filename)
    symmetry.set_output_experiments_filename(self._experiments_filename)
    symmetry.set_output_reflections_filename(self._reflections_filename)
    symmetry.set_tolerance(
      relative_length_tolerance=None, absolute_angle_tolerance=None)
    symmetry.decide_pointgroup()
    space_group = sgtbx.space_group_info(
      symbol=str(symmetry.get_pointgroup())).group()
    cb_op =  sgtbx.change_of_basis_op(symmetry.get_reindex_operator())

    self._data_manager.experiments = load.experiment_list(
      self._experiments_filename, check_format=False)
    self._data_manager.reflections = flex.reflection_table.from_pickle(
      self._reflections_filename)

    logger.info('Space group determined by dials.symmetry: %s' % space_group.info())

  def refine(self):
    # refine in correct bravais setting
    self._experiments_filename, self._reflections_filename = self._dials_refine(
      self._experiments_filename, self._reflections_filename)
    self._data_manager.experiments = load.experiment_list(
      self._experiments_filename, check_format=False)
    self._data_manager.reflections = flex.reflection_table.from_pickle(
      self._reflections_filename)

  def two_theta_refine(self):
    # two-theta refinement to get best estimate of unit cell
    self.best_unit_cell, self.best_unit_cell_esd, self._experiments_filename \
      = self._dials_two_theta_refine(
          self._experiments_filename, self._reflections_filename)
    self._data_manager.experiments = load.experiment_list(
      self._experiments_filename, check_format=False)

  @property
  def scaled_mtz(self):
    return self._scaled_mtz

  @property
  def scaled_unmerged_mtz(self):
    return self._scaled_unmerged_mtz

  @property
  def data_manager(self):
    return self._data_manager

  @staticmethod
  def _dials_refine(experiments_filename, reflections_filename):
    refiner = Refine()
    auto_logfiler(refiner)
    refiner.set_experiments_filename(experiments_filename)
    refiner.set_indexed_filename(reflections_filename)
    refiner.run()
    return refiner.get_refined_experiments_filename(), refiner.get_refined_filename()

  @staticmethod
  def _dials_two_theta_refine(experiments_filename, reflections_filename):
    tt_refiner = TwoThetaRefine()
    auto_logfiler(tt_refiner)
    tt_refiner.set_experiments([experiments_filename])
    tt_refiner.set_pickles([reflections_filename])
    tt_refiner.run()
    unit_cell = tt_refiner.get_unit_cell()
    unit_cell_esd = tt_refiner.get_unit_cell_esd()
    return unit_cell, unit_cell_esd, tt_refiner.get_output_experiments()

  def scale(self, d_min=None):
    logger.debug('Scaling with dials.scale')
    scaler = DialsScale()
    auto_logfiler(scaler)
    #scaler.set_surface_link(False) # multi-crystal
    scaler.add_experiments_json(self._experiments_filename)
    scaler.add_reflections_pickle(self._reflections_filename)
    #scaler.set_surface_tie(self._params.scaling.surface_tie)
    lmax = self._params.scaling.secondary.lmax
    if lmax:
      scaler.set_absorption_correction(True)
      scaler.set_lmax(lmax)
    else:
      scaler.set_absorption_correction(False)
    scaler.set_spacing(self._params.scaling.rotation.spacing)
    if self._params.scaling.brotation.spacing is not None:
      scaler.set_bfactor(brotation=self._params.scaling.brotation.spacing)
    if d_min is not None:
      scaler.set_resolution(d_min)
    if self._params.scaling.dials.Isigma_range is not None:
      scaler.set_isigma_selection(self._params.scaling.dials.Isigma_range)
    if self._params.scaling.dials.min_partiality is not None:
      scaler.set_min_partiality(self._params.scaling.dials.min_partiality)
    if self._params.scaling.dials.partiality_cutoff is not None:
      scaler.set_partiality_cutoff(self._params.scaling.dials.partiality_cutoff)

    scaler.set_full_matrix(False)
    if self._params.scaling.dials.model is not None:
      scaler.set_model(self._params.scaling.dials.model)
    scaler.set_outlier_rejection(self._params.scaling.dials.outlier_rejection)

    scaler.scale()
    self._scaled_mtz = scaler.get_scaled_mtz()
    self._scaled_unmerged_mtz = scaler.get_scaled_unmerged_mtz()
    self._experiments_filename = scaler.get_scaled_experiments()
    self._reflections_filename = scaler.get_scaled_reflections()
    self._data_manager.experiments = load.experiment_list(
      self._experiments_filename, check_format=False)
    self._data_manager.reflections = flex.reflection_table.from_pickle(
      self._reflections_filename)
    self._params.resolution.labels = 'IPR,SIGIPR'
    return scaler

  def estimate_resolution_limit(self):
    # see also xia2/Modules/Scaler/CommonScaler.py: CommonScaler._estimate_resolution_limit()
    from xia2.Wrappers.XIA.Merger import Merger
    params = self._params.resolution
    m = Merger()
    auto_logfiler(m)
    m.set_hklin(self._scaled_unmerged_mtz)
    m.set_limit_rmerge(params.rmerge)
    m.set_limit_completeness(params.completeness)
    m.set_limit_cc_half(params.cc_half)
    m.set_cc_half_fit(params.cc_half_fit)
    m.set_cc_half_significance_level(params.cc_half_significance_level)
    m.set_limit_isigma(params.isigma)
    m.set_limit_misigma(params.misigma)
    m.set_labels(params.labels)
    #if batch_range is not None:
      #start, end = batch_range
      #m.set_batch_range(start, end)
    m.run()

    resolution_limits = []
    reasoning = []

    if params.completeness is not None:
      r_comp = m.get_resolution_completeness()
      resolution_limits.append(r_comp)
      reasoning.append('completeness > %s' % params.completeness)

    if params.cc_half is not None:
      r_cc_half = m.get_resolution_cc_half()
      resolution_limits.append(r_cc_half)
      reasoning.append('cc_half > %s' % params.cc_half)

    if params.rmerge is not None:
      r_rm = m.get_resolution_rmerge()
      resolution_limits.append(r_rm)
      reasoning.append('rmerge > %s' % params.rmerge)

    if params.isigma is not None:
      r_uis = m.get_resolution_isigma()
      resolution_limits.append(r_uis)
      reasoning.append('unmerged <I/sigI> > %s' % params.isigma)

    if params.misigma is not None:
      r_mis = m.get_resolution_misigma()
      resolution_limits.append(r_mis)
      reasoning.append('merged <I/sigI> > %s' % params.misigma)

    if len(resolution_limits):
      resolution = max(resolution_limits)
      reasoning = [
          reason for limit, reason in zip(resolution_limits, reasoning)
          if limit >= resolution
      ]
      reasoning = ', '.join(reasoning)
    else:
      resolution = 0.0
      reasoning = None

    return resolution, reasoning

