#!/usr/bin/env bash
# Sample points (no SVIDs) from the public LICONN segmentation on this machine.
set -euo pipefail

# Workers are started as `volara-cli` from PATH, so the env with this repo
# installed must come first; otherwise they die on startup and daisy hangs.
NPS_ENV="/groups/troidl/home/troidlj/miniconda3/envs/nps"
OUTPUT_DIR="/groups/troidl/troidllab/shape_reasoning/liconn_axons_cluster_v4"

export PATH="${NPS_ENV}/bin:${PATH}"

CV_PATH="precomputed://gs://liconn-public/ExPID82_1/segmentation/231030_agg_240123"
MIP=0

NUM_WORKERS=8
FRACTION=0.001

nps --cv-path "${CV_PATH}" \
    --mip "${MIP}" \
    --fill-missing \
    --output-dir "${OUTPUT_DIR}" \
    --worker-type LocalWorker \
    --num-workers "${NUM_WORKERS}" \
    --fraction "${FRACTION}"
