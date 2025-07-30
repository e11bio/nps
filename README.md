# CLI for Point Cloud Sampling

```
pip install nps
````
### Get started


```zsh
(nps-v2) ➜  nps git:(main) ✗ nps --help
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

```bash
nps --cv-path precomputed://gs://neuroglancer-janelia-flyem-hemibrain/v1.0/segmentation
```