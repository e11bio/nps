"""
Per-block occupancy mask computed from a coarse mip level.

Reading a chunk from a (sharded) precomputed volume costs roughly the same
regardless of how many voxels are requested, so checking each block for
emptiness at sampling time does not pay off. Instead we make one pass over the
ROI at the coarsest available mip, where a single chunk covers hundreds of
sampling blocks, and record for every block whether it contains any label.
The mask is then used by :class:`SamplePoints` to skip empty blocks inside the
daisy scheduler, so workers never touch them.
"""

from concurrent.futures import ThreadPoolExecutor
from itertools import product

import numpy as np
from cloudvolume import CloudVolume
from funlib.geometry import Coordinate, Roi
from volara.datasets import CloudVolumeWrapper

# Approximate edge length, in coarse voxels, of the region read per job.
_TARGET_TILE_VOXELS = 128

def _open_coarse(store: str, mip: int, timestamp: int, agglomerate: bool) -> CloudVolume:
    return CloudVolume(
        store,
        mip=mip,
        use_https=True,
        agglomerate=agglomerate,
        timestamp=timestamp,
        fill_missing=True,  # missing chunks are, by definition, empty
        bounded=False,  # tiles at the ROI edge may poke out of the volume
    )


def _tile_job(args):
    """Read one coarse tile and return which of its blocks are non-empty."""
    vol, tile_index, block_lo, block_hi, roi_begin, roi_end, block_size, factor = args
    block_lo, block_hi = np.array(block_lo), np.array(block_hi)
    roi_begin, roi_end = np.array(roi_begin), np.array(roi_end)
    block_size, factor = np.array(block_size), np.array(factor)

    # Coarse voxel range covering all blocks in this tile (clipped to the ROI).
    fine_lo = roi_begin + block_lo * block_size
    fine_hi = np.minimum(roi_begin + block_hi * block_size, roi_end)
    coarse_lo = fine_lo // factor
    coarse_hi = -(-fine_hi // factor)  # ceil
    data = np.asarray(
        vol[tuple(slice(int(a), int(b)) for a, b in zip(coarse_lo, coarse_hi))]
    ).squeeze(axis=-1)

    out = np.zeros(block_hi - block_lo, dtype=bool)
    for idx in product(*(range(n) for n in out.shape)):
        b = block_lo + np.array(idx)
        lo = (roi_begin + b * block_size) // factor - coarse_lo
        hi = -(-(np.minimum(roi_begin + (b + 1) * block_size, roi_end)) // factor) - coarse_lo
        out[idx] = data[tuple(slice(int(a), int(c)) for a, c in zip(lo, hi))].any()
    return tile_index, out


def _dilate(mask: np.ndarray, radius: int) -> np.ndarray:
    """Binary dilation with a cube of the given radius (no scipy dependency)."""
    if radius <= 0:
        return mask
    padded = np.pad(mask, radius)
    out = np.zeros_like(mask)
    for shift in product(range(2 * radius + 1), repeat=mask.ndim):
        sl = tuple(slice(s, s + n) for s, n in zip(shift, mask.shape))
        out |= padded[sl]
    return out


def compute_block_mask(
    labels: CloudVolumeWrapper,
    roi: Roi,
    block_size: Coordinate,
    mask_mip: int | None = None,
    num_workers: int = 8,
    dilate: int = 1,
) -> np.ndarray:
    """
    Compute a boolean array, indexed by block index within ``roi``, that is
    True for blocks containing at least one non-zero label.

    Args:
        labels: The label volume that will be sampled.
        roi: ROI to be processed, in voxel coordinates of ``labels.mip``
            (i.e. the frame daisy blocks are expressed in).
        block_size: Sampling block size in the same frame.
        mask_mip: Mip level to read for the occupancy check. Defaults to the
            coarsest mip available.
        num_workers: Number of threads reading coarse tiles. Reads are I/O and
            decompression bound and release the GIL, so threads scale as well
            as processes here while avoiding multiprocessing entirely (forked
            and spawned pools both died with BrokenProcessPool on LSF nodes).
        dilate: Grow the mask by this many blocks in every direction. Guards
            against thin structures that vanish when downsampled.
    """
    base = CloudVolume(str(labels.store), mip=labels.mip, use_https=True)
    if mask_mip is None:
        mask_mip = max(base.available_mips)
    factor = np.asarray(base.mip_resolution(mask_mip)) / np.asarray(
        base.mip_resolution(labels.mip)
    )
    assert np.allclose(factor, np.round(factor)), (
        f"mip {mask_mip} resolution is not an integer multiple of mip {labels.mip}"
    )
    factor = np.round(factor).astype(int)

    roi_begin = np.array(roi.begin)
    roi_end = np.array(roi.end)
    block_size = np.array(block_size)
    n_blocks = -(-(roi_end - roi_begin) // block_size)

    # Blocks per tile per axis: enough that a tile is ~_TARGET_TILE_VOXELS wide.
    blocks_per_tile = np.maximum(
        1, _TARGET_TILE_VOXELS // np.maximum(1, block_size // factor)
    )
    n_tiles = -(-n_blocks // blocks_per_tile)

    coarse = _open_coarse(
        str(labels.store), mask_mip, labels.timestamp, labels.agglomerate
    )
    jobs = []
    for t in product(*(range(n) for n in n_tiles)):
        t = np.array(t)
        lo = t * blocks_per_tile
        hi = np.minimum(lo + blocks_per_tile, n_blocks)
        jobs.append(
            (coarse, tuple(t), tuple(lo), tuple(hi), tuple(roi_begin),
             tuple(roi_end), tuple(block_size), tuple(factor))
        )

    mask = np.zeros(n_blocks, dtype=bool)
    with ThreadPoolExecutor(max_workers=num_workers) as pool:
        for tile_index, sub in pool.map(_tile_job, jobs):
            lo = np.array(tile_index) * blocks_per_tile
            mask[tuple(slice(a, a + n) for a, n in zip(lo, sub.shape))] = sub

    return _dilate(mask, dilate)
