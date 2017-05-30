# -*- coding: utf-8 -*-
import numpy as np
from copy import deepcopy

import utilities.misc_io as io
from .base_sampler import BaseSampler
from .rand_rotation import RandomRotationLayer
from .rand_spatial_scaling import RandomSpatialScalingLayer
from .uniform_sampler import rand_spatial_coordinates
from .spatial_location_check import SpatialLocationCheckLayer


class SelectiveSampler(BaseSampler):
    """
    This class generators samples by sampling each input volume
    the output samples satisfy constraints such as number of
    unique values in training label
    (currently 4D input is supported, Height x Width x Depth x Modality)
    """

    def __init__(self,
                 patch,
                 volume_loader,
                 spatial_location_check=None,
                 data_augmentation_methods=['rotation', 'spatial_scaling'],
                 patch_per_volume=1,
                 name="selective_sampler"):

        super(SelectiveSampler, self).__init__(patch=patch, name=name)
        self.volume_loader = volume_loader

        self.spatial_location_check = spatial_location_check
        self.data_augmentation_layers = []
        if data_augmentation_methods is not None:
            for method in data_augmentation_methods:
                if method == 'rotation':
                    self.data_augmentation_layers.append(
                        RandomRotationLayer(min_angle=-10.0, max_angle=10.0))
                elif method == 'spatial_scaling':
                    self.data_augmentation_layers.append(
                        RandomSpatialScalingLayer(max_percentage=10.0))
                else:
                    raise ValueError('unkown data augmentation method')

        self.patch_per_volume = patch_per_volume

    def layer_op(self, batch_size=1):
        """
         problems:
            check how many modalities available
            check the colon operator
            automatically handle mutlimodal by matching dims?
        """
        # batch_size is needed here so that it generates total number of
        # N samples where (N % batch_size) == 0

        spatial_rank = self.patch.spatial_rank
        local_layers = [deepcopy(x) for x in self.data_augmentation_layers]
        patch = deepcopy(self.patch)
        spatial_location_check = deepcopy(self.spatial_location_check)
        while self.volume_loader.has_next:
            img, seg, weight_map, idx = self.volume_loader()

            # to make sure all volumetric data have the same spatial dims
            # and match volumetric data shapes to the patch definition
            # (the matched result will be either 3d or 4d)
            img.spatial_rank = spatial_rank
            img.data = io.match_volume_shape_to_patch_definition(
                img.data, self.patch.full_image_shape)
            if img.data.ndim - spatial_rank > 1:
                raise NotImplementedError
                # time series data are not supported
            if seg is not None:
                seg.spatial_rank = spatial_rank
                seg.data = io.match_volume_shape_to_patch_definition(
                    seg.data, self.patch.full_label_shape)
            if weight_map is not None:
                weight_map.spatial_rank = spatial_rank
                weight_map.data = io.match_volume_shape_to_patch_definition(
                    weight_map.data, self.patch.full_weight_map_shape)

            # apply volume level augmentation
            for aug in local_layers:
                aug.randomise(spatial_rank=spatial_rank)
                img, seg, weight_map = aug(img), aug(seg), aug(weight_map)

            # to generate 'patch_per_volume' samples satisfying
            # the conditions specified by spatial_location_check instance:
            # 'n_locations_to_check' samples are randomly sampled
            # and checked. This sampling and checking process is repeated
            # for 10 times at most.
            locations = []
            n_locations_to_check = self.patch_per_volume * 10
            spatial_location_check.sampling_from(seg.data)
            n_trials = 10
            while len(locations) < self.patch_per_volume and n_trials > 0:
                # generates random spatial coordinates
                candidate_locations = rand_spatial_coordinates(
                    img.spatial_rank,
                    img.data.shape,
                    patch.image_size,
                    n_locations_to_check)
                is_valid = [spatial_location_check(location, spatial_rank)
                            for location in candidate_locations]
                is_valid = np.asarray(is_valid, dtype=bool)
                print("{} good samples from {} candidates".format(
                    np.sum(is_valid), len(candidate_locations)))
                for loc in candidate_locations[is_valid]:
                    locations.append(loc)
                n_trials -= 1
            locations = np.vstack(locations)

            for loc in locations:
                patch.set_data(idx, loc, img, seg, weight_map)
                yield patch
