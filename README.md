[![pypi](https://badge.fury.io/py/nps-cli.svg)](https://badge.fury.io/py/nps-cli)
[![Python Version](https://img.shields.io/pypi/pyversions/nps-cli.svg)](https://pypi.org/project/nps-cli/)

# CLI for Distributed Point Cloud Sampling

```
pip install nps-cli
````
### Get started

```zsh
nps --help
Usage: nps [OPTIONS]

Options:
  --cv-path TEXT                  Path to CloudVolume data.  [required]
  --svid-cv-path TEXT             Separate CloudVolume path holding supervoxel
                                  IDs (e.g. a precomputed watershed volume).
                                  Implies SVID sampling. Must share the voxel
                                  grid of --cv-path at the chosen mip.
  --mip INTEGER                   MIP level to use.  [default: 0]
  --timestamp INTEGER             Optional timestamp for the dataset version
                                  (graphene only).
  --sample_svids                  Sample SVIDs in addition to points (default:
                                  False). Without --svid-cv-path, supervoxels
                                  are read from --cv-path with
                                  agglomerate=False (graphene only).
  --fill-missing                  Returns 0 for missing chunks, if not set, EmptyVolumeException will be thrown for missing chunks 
  -o, --output-dir DIRECTORY      Output directory.  [default: ./nps_output]
  --worker-type [LocalWorker|LSFWorker|SlurmWorker]
                                  Type of worker to use for sampling.
                                  [default: LocalWorker]
  --num-workers INTEGER           Number of workers for blockwise sampling.
                                  [default: 8]
  --cpus-per-worker INTEGER       Number of CPUs per worker.  [default: 4]
  --queue TEXT                    Queue name (for LSF backend).  [default:
                                  local]
  --fraction FLOAT                Fraction of points to sample [0.0, 1.0].
                                  [default: 0.001]
  --bbox INTEGER...               Bounding box: begin_x begin_y begin_z
                                  end_x end_y end_z (in voxels).
  --skip-empty / --no-skip-empty  Pre-scan a coarse mip to find blocks without
                                  labels and skip them.  [default: skip-empty]
  --mask-mip INTEGER              Mip level used for the empty-block pre-scan.
                                  [default: coarsest available]
  --block-mask FILE               Reuse an existing block_mask.npy from a
                                  previous run with identical --bbox, --block-
                                  size and --mip instead of re-scanning.
  --block-size INTEGER...         Block size in voxels (X Y Z).  [default:
                                  128, 128, 128]
  -h, --help                      Show this message and exit.
```

### Example usage

```bash
nps --cv-path precomputed://gs://neuroglancer-janelia-flyem-hemibrain/v1.0/segmentation
```

Sample point clouds within a FlyEM Hemibrain subvolume: 

```bash
nps --cv-path precomputed://gs://neuroglancer-janelia-flyem-hemibrain/v1.0/segmentation --bbox 15347 19712 18606 15859 20224 19118 --fraction 0.01
```

Sample points from an agglomerated volume and attach supervoxel IDs looked up in a separate precomputed volume (points are sampled from `--cv-path` only; `--svid-cv-path` is used for the per-point lookup):

```bash
nps --cv-path precomputed://gs://<bucket>/segmentation/agglomerated \
    --svid-cv-path precomputed://gs://<bucket>/segmentation/supervoxels
```

For graphene volumes, `--sample_svids` alone reads the supervoxels from the same store with `agglomerate=False`.

### Skipping empty blocks

Most of a volume's bounding box is usually empty, and reading a chunk from a (sharded) precomputed volume costs about the same however few voxels you ask for. By default `nps` therefore first scans the ROI at the coarsest mip, builds a per-block occupancy mask (saved as `block_mask.npy` in the output directory), and never dispatches empty blocks to workers. The mask is dilated by one block so thin structures lost in downsampling are still sampled. Pass `--no-skip-empty` to disable the scan, or `--block-mask <path>` to reuse a mask from an earlier run with the same `--bbox`, `--block-size` and `--mip`.

### Example

```
./examples/scripts/liconn_local.sh          # points only
./examples/scripts/liconn_svids_local.sh    # points + SVIDs from a separate precomputed volume
./examples/scripts/flywire_cluster.sh       # points + SVIDs from a graphene volume on LSF
```

### Reading Point Clouds

Please refer to the [pocaduck](https://github.com/JaneliaSciComp/pocaduck?tab=readme-ov-file#querying-point-clouds) repo on how to read point clouds from the output directory:

```python
from pocaduck import Query

# Create a query object
query = Query(storage_config=<PATH>) # path to folder where nps output is stored

# Get all available labels
labels = query.get_labels()
print(f"Available labels: {labels}")

# Get all points for a label (aggregated across all blocks)
points = query.get_points(label=12345)
print(f"Retrieved {points.shape[0]} points for label 12345")

# Close the query connection when done
query.close()
```

For optimized point cloud reading, consider [this](https://github.com/JaneliaSciComp/pocaduck?tab=readme-ov-file#running-the-optimization-pipeline).


### Deploy
```python
python -m build
twine upload dist/*
```
