import os
import numpy as np
import click
import time

from nps.blockwise.sample_points import SamplePoints
from volara.datasets import CloudVolumeWrapper
from volara.workers import LSFWorker, LocalWorker, SlurmWorker

@click.command(context_settings=dict(help_option_names=['-h', '--help']))
@click.option('--cv-path', required=True, help='Path to CloudVolume data.')
@click.option('--mip', default=0, type=int, show_default=True, help='MIP level to use.')
@click.option('--timestamp', default=int(time.time()), help='Optional timestamp for the dataset version (graphene only).')
@click.option('--sample_svids', is_flag=True, default=False, help='Sample SVIDs in addition to points (default: False).')
@click.option('--output-dir', '-o', default='./nps_output', show_default=True, type=click.Path(file_okay=False, writable=True), help='Output directory.')
@click.option('--worker-type', default='LocalWorker', show_default=True, type=click.Choice(['LocalWorker', 'LSFWorker', 'SlurmWorker'], case_sensitive=True), help='Type of worker to use for sampling.')
@click.option('--num-workers', default=8, show_default=True, type=int, help='Number of workers for blockwise sampling.')
@click.option('--cpus-per-worker', default=4, show_default=True, type=int, help='Number of CPUs per worker.')
@click.option('--queue', default='local', show_default=True, help='Queue name (for LSF backend).')
@click.option('--fraction', default=0.001, show_default=True, type=float, help='Fraction of points to sample [0.0, 1.0].')
@click.option('--block-size', nargs=3, type=int, default=(128, 128, 128), show_default=True, help='Block size in voxels (X Y Z).')
def main(cv_path, mip, timestamp, output_dir, num_workers, cpus_per_worker, queue, fraction, block_size, sample_svids, worker_type):

    click.echo(f"Reading CloudVolume at {cv_path} (mip={mip}, timestamp={timestamp})")

    labels_name = os.path.dirname(output_dir) + "_labels"
    labels = CloudVolumeWrapper(data_name=labels_name, store=cv_path, mip=mip, timestamp=timestamp)

    if sample_svids:
        click.echo("Sampling SVIDs in addition to points...")
        svids_name = os.path.dirname(output_dir) + "_svids"
        svids = CloudVolumeWrapper(data_name=svids_name, store=cv_path, mip=mip, timestamp=timestamp, agglomerate=False)
    else:
        click.echo("Sampling points only (no SVIDs)...")
        svids = None

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    if worker_type == 'LocalWorker':
        click.echo("Using LocalWorker for sampling.")
        worker_config = LocalWorker()
    elif worker_type == 'LSFWorker':
        click.echo(f"Using LSFWorker with queue '{queue}' and {cpus_per_worker} CPUs per worker.")
        worker_config = LSFWorker(queue=queue, num_cpus=cpus_per_worker)
    elif worker_type == 'SlurmWorker':
        click.echo(f"Using SlurmWorker with queue '{queue}' and {cpus_per_worker} CPUs per worker.")
        worker_config = SlurmWorker(queue=queue, num_cpus=cpus_per_worker)

    task = SamplePoints(
        labels=labels,
        svids=svids,
        block_size=np.array(block_size),
        num_workers=num_workers,
        out_dir=output_dir,
        fraction=fraction,
        worker_config=worker_config
    )

    click.echo("Running task...")
    task.drop()
    task.run_blockwise(multiprocessing=True)
    click.secho("✅ Done!", fg='green')


if __name__ == "__main__":
    main()
