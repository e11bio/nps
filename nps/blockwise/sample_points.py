import glob
import logging
import os
import shutil
import uuid
from contextlib import contextmanager
from typing import Literal

import daisy
import duckdb
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from daisy import Block
from funlib.geometry import Coordinate, Roi
from volara.blockwise import BlockwiseTask
from volara.datasets import CloudVolumeWrapper, Dataset
from volara.utils import PydanticCoordinate

_INDEX_SCHEMA = """
    CREATE TABLE IF NOT EXISTS {name} (
        label UBIGINT,
        block_id VARCHAR,
        file_path VARCHAR,
        point_count UBIGINT
    )
"""


class SamplePoints(BlockwiseTask):
    task_type: Literal["sample_pc"] = "sample_pc"
    out_dir: str
    labels: CloudVolumeWrapper
    svids: CloudVolumeWrapper | None = None
    block_mask: str | None = None
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
        # init() recreates the directory when the task is run.
        shutil.rmtree(self.out_dir, ignore_errors=True)

    def check_block_func(self):
        """
        Daisy calls this in the scheduler before dispatching a block; returning
        True means "already done". If a block mask is given, report empty blocks
        as done so they are never sent to a worker.
        """
        base = super().check_block_func()
        if self.block_mask is None:
            return base

        mask = np.load(self.block_mask)
        roi_begin = np.array(self.write_roi.begin)
        block_size = np.array(self.block_size)

        def check_block(block: Block) -> bool:
            index = (np.array(block.write_roi.begin) - roi_begin) // block_size
            if not mask[tuple(index)]:
                return True
            return base(block)

        return check_block

    @property
    def output_datasets(self) -> list[Dataset]:
        return []

    def sample_pc_in_block(self, block: Block, labels: np.ndarray, svids: np.ndarray | None, offset: Coordinate, writer: "_PointWriter"):
        block_id = block.block_id[1]

        seg_ids, pts = self.sample_segment_points(labels, self.fraction)
        logging.info(f"sampled {len(pts)} points in block {block_id}")

        packed_pts = (pts + np.array(offset)).astype(np.uint64)
        if self.svids is not None:
            sampled_svids = svids[pts[:, 0], pts[:, 1], pts[:, 2]].reshape(-1, 1)
            packed_pts = np.concatenate((packed_pts, sampled_svids.astype(np.uint64)), axis=1)

        writer.write(block_id, seg_ids, packed_pts)

    def init(self):
        os.makedirs(self.out_dir, exist_ok=True)

    @contextmanager
    def process_block_func(self):
        data = self.labels.array("r")
        if self.svids is not None:
            supervoxels = self.svids.array("r")

        try:
            worker_id = daisy.Context.from_env()["worker_id"]
        except KeyError:
            worker_id = 0
        # One writer per worker process instead of a pocaduck Ingestor per
        # block, which re-read and re-wrote the worker's whole parquet file
        # and ran two DuckDB queries per segment on every block.
        writer = _PointWriter(self.out_dir, worker_id)

        def process_block(block: Block):
            # Index with the Roi (world/absolute voxel coords), not with
            # to_slices(): numpy-style keys on a funlib Array are zero-based and
            # would read from the wrong place on volumes with a voxel offset.
            # Only squeeze the channel axis; edge blocks can be 1 voxel thick.
            labels = np.asarray(data[block.write_roi]).squeeze(axis=-1)

            offset = block.write_roi.get_begin()

            if self.svids is not None:
                s = np.asarray(supervoxels[block.write_roi]).squeeze(axis=-1)
                assert s.shape == labels.shape, (
                    f"label block {labels.shape} and svid block {s.shape} differ in "
                    f"{block.write_roi}; the label and supervoxel volumes must share "
                    "resolution and offset at the chosen mip"
                )
            else:
                s = None

            self.sample_pc_in_block(block, labels, s, offset, writer)

        # Index consolidation happens once in the driver after all blocks are
        # done (see consolidate_indexes), not concurrently in every worker.
        yield process_block

    def sample_segment_points(self, labels, fraction, background=0):
        """
        Sample max(1, int(n * fraction)) voxels without replacement from every
        segment with n voxels. Returns the segment ID of every sampled point
        and the (N, 3) voxel coordinates within ``labels``.

        Vectorized: one sort over the foreground voxels instead of one full
        ``labels == seg`` scan per segment.
        """
        flat = labels.ravel()
        idx = np.flatnonzero(flat != background) if background is not None else np.arange(flat.size)
        vals = flat[idx]

        # Shuffle, then stable-sort by segment: groups segments together with a
        # random order inside each group, so the first k of a group are a
        # uniform sample without replacement.
        perm = np.random.permutation(len(idx))
        perm = perm[np.argsort(vals[perm], kind="stable")]
        idx, vals = idx[perm], vals[perm]

        _, starts, counts = np.unique(vals, return_index=True, return_counts=True)
        k = np.maximum(1, (counts * fraction).astype(np.int64))
        rank = np.arange(len(vals)) - np.repeat(starts, counts)
        keep = rank < np.repeat(k, counts)

        coords = np.column_stack(np.unravel_index(idx[keep], labels.shape))
        return vals[keep], coords


class _PointWriter:
    """
    Writes sampled points of one worker in the layout of pocaduck's Ingestor
    (``worker_<id>/data/*.parquet`` plus ``worker_<id>/index_<id>.db``), so
    :func:`consolidate_indexes` and ``pocaduck.Query`` work unchanged.

    Every block is written (parquet first, then its index rows) before the
    block returns: daisy marks a block done as soon as process_block returns
    and does not wait for worker teardown, so buffering across blocks would
    lose data.
    """

    def __init__(self, out_dir: str, worker_id):
        worker_dir = os.path.join(out_dir, f"worker_{worker_id}")
        self.data_dir = os.path.join(worker_dir, "data")
        self.db_path = os.path.join(worker_dir, f"index_{worker_id}.db")
        os.makedirs(self.data_dir, exist_ok=True)
        # Unique prefix: a restarted worker can reuse a worker_id and must not
        # overwrite files of a previous run.
        self.prefix = f"{worker_id}-{uuid.uuid4().hex[:8]}"

    def write(self, block_id, seg_ids: np.ndarray, points: np.ndarray):
        if len(points) == 0:
            return
        file_path = os.path.join(self.data_dir, f"{self.prefix}-{block_id}.parquet")
        data = pa.FixedSizeListArray.from_arrays(pa.array(points.ravel()), points.shape[1])
        table = pa.table({
            "label": seg_ids.astype(np.int64),
            "block_id": np.full(len(points), block_id, dtype=np.int64),
            # Same list<uint64> column the pocaduck Ingestor writes.
            "data": data.cast(pa.list_(pa.uint64())),
        })
        # Write-then-rename so a killed worker never leaves a truncated file.
        pq.write_table(table, file_path + ".tmp")
        os.replace(file_path + ".tmp", file_path)

        segs, counts = np.unique(seg_ids, return_counts=True)
        index = pd.DataFrame({
            "label": segs.astype(np.uint64),
            "block_id": str(block_id),
            "file_path": file_path,
            "point_count": counts.astype(np.uint64),
        })
        # Short-lived connection: the driver attaches these files for
        # consolidation while worker processes may still be alive.
        con = duckdb.connect(self.db_path)
        con.execute(_INDEX_SCHEMA.format(name="point_cloud_index"))
        con.register("new_rows", index)
        con.execute("INSERT INTO point_cloud_index SELECT * FROM new_rows")
        con.close()


def consolidate_indexes(out_dir: str) -> str:
    """
    Merge all worker indexes into ``unified_index.db`` (what pocaduck's Query
    reads). Replaces ``Ingestor.consolidate_indexes``, which pulls every row
    through Python and was run concurrently by every worker.
    """
    output_path = os.path.join(out_dir, "unified_index.db")
    if os.path.exists(output_path):
        os.remove(output_path)
    con = duckdb.connect(output_path)
    con.execute(_INDEX_SCHEMA.format(name="point_cloud_index"))
    for path in sorted(glob.glob(os.path.join(out_dir, "worker_*", "index_*.db"))):
        con.execute(f"ATTACH '{path}' AS w (READ_ONLY)")
        con.execute("INSERT INTO point_cloud_index SELECT * FROM w.point_cloud_index")
        con.execute("DETACH w")
    con.close()
    return output_path