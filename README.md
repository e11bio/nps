[![pypi](https://badge.fury.io/py/nps-cli.svg)](https://badge.fury.io/py/nps-cli)
[![Python Version](https://img.shields.io/pypi/pyversions/nps-cli.svg)](https://pypi.org/project/nps-cli/)

# nps: distributed point cloud sampling

`nps` samples point clouds of every segment in a large segmentation volumes
* Compatible with [CloudVolume](https://github.com/seung-lab/cloud-volume) (precomputed or graphene).
* It processes the volume blockwise on local, LSF or Slurm workers and writes the points in [pocaduck](https://github.com/JaneliaSciComp/pocaduck) format.

```bash
pip install nps-cli
nps --help
```

## Usage

```bash
# Whole volume
nps --cv-path precomputed://gs://neuroglancer-janelia-flyem-hemibrain/v1.0/segmentation

# Subvolume (begin_x begin_y begin_z end_x end_y end_z, in voxels), 1% of each segment
nps --cv-path precomputed://gs://neuroglancer-janelia-flyem-hemibrain/v1.0/segmentation \
    --bbox 15347 19712 18606 15859 20224 19118 --fraction 0.01

# Also store the supervoxel ID of every point, looked up in a separate volume
# that shares the voxel grid of --cv-path
nps --cv-path precomputed://gs://<bucket>/agglomerated \
    --svid-cv-path precomputed://gs://<bucket>/supervoxels

# Graphene: read supervoxels from the same volume (agglomerate=False)
nps --cv-path graphene://https://<server>/segmentation/table/<table> --sample_svids
```

Key options (run `nps --help` for all of them):

| Option | Default | Meaning |
| --- | --- | --- |
| `--fraction` | `0.001` | Fraction of each segment's voxels to sample (at least 1 per segment and block). |
| `--mip` | `0` | Resolution level to sample at. Coordinates are voxels of this mip. |
| `--bbox` | whole volume | ROI in voxels. |
| `--block-size` | `128 128 128` | Block size per task, in voxels. |
| `--worker-type` / `--num-workers` / `--cpus-per-worker` / `--queue` | `LocalWorker` / `8` / `4` / `local` | Where and how the blocks are processed. |
| `--fill-missing` | off | Treat missing chunks as empty instead of raising an error. |
| `--overwrite` | off | Delete points of an earlier run in `--output-dir` instead of refusing to start. |
| `--skip-empty` / `--block-mask` / `--mask-mip` | on | Skipping empty blocks, see below. |

### Output

```
<output-dir>/
  block_mask.npy            # occupancy mask from the empty-block pre-scan
  points/
    unified_index.db        # pocaduck index over all workers
    worker_<id>/...         # parquet files + per-worker index
```

Each point is `[x, y, z]`, or `[x, y, z, svid]` when SVIDs are sampled, stored under its segment label.

`nps` refuses to write into an `--output-dir` that already holds points, since every
run re-samples all blocks and old points would show up as duplicates. Pass
`--overwrite` to delete them first.

### Skipping empty blocks

Before sampling, `nps` scans the ROI at a coarse mip (`--mask-mip`, default the
coarsest one) and never dispatches blocks without labels. The mask is dilated by
one block, so thin structures lost in downsampling are still sampled. Use
`--no-skip-empty` to disable the scan, or `--block-mask <path>` to reuse a
`block_mask.npy` from an earlier run with the same `--bbox`, `--block-size` and `--mip`.

## Reading point clouds

```python
from pocaduck import Query, StorageConfig

query = Query(storage_config=StorageConfig(base_path="<output-dir>/points"))
labels = query.get_labels()
points = query.get_points(label=12345)  # all points of one segment
query.close()
```

See the [pocaduck docs](https://github.com/JaneliaSciComp/pocaduck?tab=readme-ov-file#querying-point-clouds)
for more, including [optimizing](https://github.com/JaneliaSciComp/pocaduck?tab=readme-ov-file#running-the-optimization-pipeline) the storage for fast reads.

## Example scripts

| Script | What it does |
| --- | --- |
| [`liconn_local.sh`](scripts/liconn_local.sh) | Points only, local workers |
| [`liconn_svids_local.sh`](scripts/liconn_svids_local.sh) | Points + SVIDs from a separate precomputed volume |
| [`flywire_cluster.sh`](scripts/flywire_cluster.sh) | Points + SVIDs for FlyWire on LSF (`LABEL_NAME=flywire_v141_m783` for the 2023 snapshot) |

## Release

```bash
pip install -e ".[dev]"
python -m build
twine upload dist/*
```
