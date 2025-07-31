# CLI for Point Cloud Sampling

```
pip install nps-cli
````
### Get started

```zsh
nps --help
Usage: nps [OPTIONS]

Options:
  --cv-path TEXT                  Path to CloudVolume data.  [required]
  --mip INTEGER                   MIP level to use.  [default: 0]
  --timestamp INTEGER             Optional timestamp for the dataset version
                                  (graphene only).
  --sample_svids                  Sample SVIDs in addition to points (default:
                                  False).
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
  --block-size INTEGER...         Block size in voxels (X Y Z).  [default:
                                  128, 128, 128]
  -h, --help                      Show this message and exit.
```

### Example usage

```bash
nps --cv-path precomputed://gs://neuroglancer-janelia-flyem-hemibrain/v1.0/segmentation
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