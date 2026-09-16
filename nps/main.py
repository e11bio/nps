import os
import numpy as np
import click
import time

from nps.blockwise.sample_points import SamplePoints
from nps.blockwise.block_mask import compute_block_mask
from funlib.geometry import Coordinate, Roi
from volara.datasets import CloudVolumeWrapper
from volara.workers import LSFWorker, LocalWorker, SlurmWorker

@click.command(context_settings=dict(help_option_names=['-h', '--help']))
@click.option('--cv-path', required=True, help='Path to CloudVolume data.')
@click.option('--svid-cv-path', default=None, help='Separate CloudVolume path holding supervoxel IDs (e.g. a precomputed watershed volume). Implies SVID sampling. Must share the voxel grid of --cv-path at the chosen mip.')
@click.option('--mip', default=0, type=int, show_default=True, help='MIP level to use.')
@click.option('--timestamp', default=int(time.time()), help='Optional timestamp for the dataset version (graphene only).')
@click.option('--sample_svids', is_flag=True, default=False, help='Sample SVIDs in addition to points (default: False). Without --svid-cv-path, supervoxels are read from --cv-path with agglomerate=False (graphene only).')
@click.option('--fill-missing', is_flag=True, default=False, help='Accomodates downloading missing tiles (default: False).')
@click.option('--output-dir', '-o', default='./nps_output', show_default=True, type=click.Path(file_okay=False, writable=True), help='Output directory.')
@click.option('--worker-type', default='LocalWorker', show_default=True, type=click.Choice(['LocalWorker', 'LSFWorker', 'SlurmWorker'], case_sensitive=True), help='Type of worker to use for sampling.')
@click.option('--num-workers', default=8, show_default=True, type=int, help='Number of workers for blockwise sampling.')
@click.option('--cpus-per-worker', default=4, show_default=True, type=int, help='Number of CPUs per worker.')
@click.option('--queue', default='local', show_default=True, help='Queue name (for LSF backend).')
@click.option('--fraction', default=0.001, show_default=True, type=float, help='Fraction of points to sample [0.0, 1.0].')
@click.option('--block-size', nargs=3, type=int, default=(128, 128, 128), show_default=True, help='Block size in voxels (X Y Z).')
@click.option('--bbox', nargs=6, type=int, default=None, help='Bounding box: begin_x begin_y begin_z end_x end_y end_z (in voxels).')
@click.option('--skip-empty/--no-skip-empty', default=True, show_default=True, help='Pre-scan a coarse mip to find blocks without labels and skip them.')
@click.option('--mask-mip', default=None, type=int, help='Mip level used for the empty-block pre-scan. [default: coarsest available]')
@click.option('--block-mask', default=None, type=click.Path(exists=True, dir_okay=False), help='Reuse an existing block_mask.npy from a previous run with identical --bbox, --block-size and --mip instead of re-scanning.')
def main(cv_path, svid_cv_path, mip, timestamp, output_dir, num_workers, cpus_per_worker, queue, fraction, block_size, sample_svids, worker_type, bbox, fill_missing, skip_empty, mask_mip, block_mask):

    output_dir = os.path.abspath(output_dir)
    points_dir = os.path.join(output_dir, 'points')
    os.makedirs(points_dir, exist_ok=True)

    click.echo(f"Reading CloudVolume at {cv_path} (mip={mip}, timestamp={timestamp})")

    base = os.path.basename(output_dir)
    common = dict(mip=mip, timestamp=timestamp, fill_missing=fill_missing)
    labels = CloudVolumeWrapper(data_name=base + "_labels", store=cv_path, **common)

    if sample_svids or svid_cv_path:
        svid_store = svid_cv_path or cv_path
        click.echo(f"Sampling SVIDs in addition to points from {svid_store}...")
        # agglomerate=False selects the watershed layer for graphene and is
        # ignored by precomputed volumes, so one code path serves both cases.
        svids = CloudVolumeWrapper(data_name=base + "_svids", store=svid_store, agglomerate=False, **common)
    else:
        click.echo("Sampling points only (no SVIDs)...")
        svids = None

    if worker_type == 'LocalWorker':
        click.echo("Using LocalWorker for sampling.")
        worker_config = LocalWorker()
    elif worker_type == 'LSFWorker':
        click.echo(f"Using LSFWorker with queue '{queue}' and {cpus_per_worker} CPUs per worker.")
        worker_config = LSFWorker(queue=queue, num_cpus=cpus_per_worker)
    elif worker_type == 'SlurmWorker':
        click.echo(f"Using SlurmWorker with queue '{queue}' and {cpus_per_worker} CPUs per worker.")
        worker_config = SlurmWorker(queue=queue, num_cpus=cpus_per_worker)

    roi = None
    if bbox is not None:
        begin = bbox[:3]
        end = bbox[3:]
        shape = tuple(e - b for b, e in zip(begin, end))
        roi = (begin, shape)

    if block_mask is None and skip_empty:
        total_roi = labels.array("r").roi
        if roi is not None:
            total_roi = total_roi.intersect(Roi(*roi))
        click.echo(f"Scanning mip {mask_mip if mask_mip is not None else 'coarsest'} for empty blocks in {total_roi}...")
        mask = compute_block_mask(labels, total_roi, Coordinate(*block_size), mask_mip=mask_mip, num_workers=num_workers)
        block_mask = os.path.join(output_dir, "block_mask.npy")
        np.save(block_mask, mask)
        click.echo(f"{mask.sum():,} of {mask.size:,} blocks ({mask.mean():.0%}) contain labels; the rest will be skipped. Mask saved to {block_mask}")
    elif block_mask is not None:
        click.echo(f"Using block mask {block_mask}")

    task = SamplePoints(
        labels=labels,
        svids=svids,
        block_mask=block_mask,
        block_size=np.array(block_size),
        num_workers=num_workers,
        out_dir=points_dir,
        fraction=fraction,
        worker_config=worker_config,
        roi=roi,
    )

    click.echo("Running task...")
    task.drop()
    task.run_blockwise(multiprocessing=True)
    click.secho("✅ Done!", fg='green')


if __name__ == "__main__":
    main()
