#!/usr/bin/env bash
# Sample points from an agglomerated precomputed volume and look up the
# supervoxel ID of every point in a separate precomputed watershed volume.
# Both volumes must share resolution and offset at the chosen MIP.
set -euo pipefail

# Workers are started as `volara-cli` from PATH, so the env with this repo
# installed must come first; otherwise they die on startup and daisy hangs.
NPS_ENV="/groups/troidl/home/troidlj/miniconda3/envs/nps"
OUTPUT_DIR="/groups/troidl/troidllab/shape_reasoning/liconn_svids_local"

export PATH="${NPS_ENV}/bin:${PATH}"

CV_PATH="precomputed://gs://liconn-public/ExPID82_1/segmentation/231030_agg_240123"
SVID_CV_PATH="precomputed://gs://liconn-public/ExPID82_1/segmentation/<supervoxel-volume>"  # TODO: set to the watershed/supervoxel volume
MIP=0

NUM_WORKERS=8
FRACTION=0.001

nps --cv-path "${CV_PATH}" \
    --svid-cv-path "${SVID_CV_PATH}" \
    --mip "${MIP}" \
    --fill-missing \
    --output-dir "${OUTPUT_DIR}" \
    --worker-type LocalWorker \
    --num-workers "${NUM_WORKERS}" \
    --fraction "${FRACTION}"
