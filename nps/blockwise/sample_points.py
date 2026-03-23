from contextlib import contextmanager
from typing import Literal

import numpy as np
import os
import logging
import daisy

from funlib.geometry import Coordinate, Roi
from volara.blockwise import BlockwiseTask
from volara.datasets import Dataset, CloudVolumeWrapper
from volara.utils import PydanticCoordinate
from daisy import Block
from pocaduck import StorageConfig, Ingestor


class SamplePoints(BlockwiseTask):
    task_type: Literal["sample_pc"] = "sample_pc"
    out_dir: str
    labels: CloudVolumeWrapper
    svids: CloudVolumeWrapper | None = None
    block_size: PydanticCoordinate
    fraction: float
    fit: Literal["shrink"] = "shrink"
    read_write_conflict: Literal[False] = False

    @property
    def task_name(self) -> str:
        return f"{self.labels.name}-{self.task_type}"

    @property
    def write_roi(self) -> Roi:
        total_roi = self.labels.array("r").roi
        if self.roi is not None:
            total_roi = total_roi.intersect(self.roi)
        return total_roi


    @property
    def voxel_size(self) -> Coordinate:
        return self.labels.voxel_size

    @property
    def write_size(self) -> Coordinate:
        return self.block_size

    @property
    def context_size(self) -> Coordinate:
        return Coordinate((0,) * self.write_size.dims)

    def drop_artifacts(self):
        pass

    @property
    def output_datasets(self) -> list[Dataset]:
        return []

    def sample_pc_in_block(self, block: Block, labels: np.ndarray, svids: np.ndarray | None, offset: Coordinate):
        block_id = block.block_id[1]
        try:
            context = daisy.Context.from_env()
            worker_id = context["worker_id"]
        except KeyError:
            worker_id = 0 

        logging.info(f"got {len(np.unique(labels))} in {block_id}")
        storage_config = StorageConfig(base_path=self.out_dir)
        ingestor = Ingestor(storage_config, worker_id=worker_id)
        sampled_points = self.sample_segment_points(labels, self.fraction)
        
        for seg, pts in sampled_points.items():
            packed_pts = pts + offset
            packed_pts = packed_pts.astype(np.uint64)
            
            if self.svids is not None:
                x, y, z = pts[:, 0], pts[:, 1], pts[:, 2]
                sampled_svids = svids[x, y, z].reshape(-1, 1)
                packed_pts = np.concatenate((packed_pts, sampled_svids), axis=1)
        
            ingestor.write(label=seg, block_id=block_id, points=packed_pts)
        ingestor.finalize()

    def init(self):
        os.makedirs(self.out_dir, exist_ok=True)

    @contextmanager
    def process_block_func(self):
        data = self.labels.array("r")
        if self.svids is not None:
            supervoxels = self.svids.array("r")

        def process_block(block: Block):
            labels = data[block.write_roi.to_slices()]
            labels = np.array(labels).squeeze()

            offset = block.write_roi.get_begin()

            if self.svids is not None:
                s = supervoxels[block.write_roi.to_slices()]
                s = np.array(s).squeeze()
            else:
                s = None

            self.sample_pc_in_block(block, labels, s, offset)

        yield process_block

        storage_config = StorageConfig(base_path=self.out_dir)
        Ingestor.consolidate_indexes(storage_config)

    def sample_segment_points(self, labels, fraction, background=0, replace=False):
        segment_ids = np.unique(labels)
        if background is not None:
            segment_ids = segment_ids[segment_ids != background]

        segment_points = {}

        for seg in segment_ids:
            coords = np.column_stack(np.where(labels == seg))
            num_points = coords.shape[0]

            k = max(1, int(num_points * fraction))

            if num_points > k:
                selected_idx = np.random.choice(num_points, size=k, replace=replace)
                sampled = coords[selected_idx]
            else:
                sampled = coords

            segment_points[str(seg)] = sampled

        return segment_points