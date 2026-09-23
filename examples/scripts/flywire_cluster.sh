#!/usr/bin/env bash
# Sample points from the local FlyWire v141 precomputed snapshot and attach the
# supervoxel ID of every point from the local watershed volume. Every point is
# stored as [x, y, z, svid] (mip-0 voxels) under its agglomerated label.
#
# Both volumes share the same grid at mip 0 (16x16x40 nm, offset 5100 1440 16),
# which --svid-cv-path requires. The label snapshot is agglomerated, the
# watershed volume holds the supervoxels (every supervoxel maps to exactly one
# label). Swap LABEL_NAME for flywire_v141_m783 to sample the 2023 snapshot.
#
# Run from an LSF submit host (e.g. a cluster login node). The driver is
# submitted with bsub; it schedules the blocks and submits every worker as its
# own LSF job (NUM_WORKERS jobs in total, visible in `bjobs`). Set
# WORKER_TYPE=LocalWorker to run everything on the current machine instead.
set -euo pipefail

RUN_NAME="sampling_flywire_v141_$(openssl rand -hex 2)"
CHARGE_CODE="miaai"
QUEUE="local"
WORKER_TYPE="${WORKER_TYPE:-LSFWorker}"

# volara submits the worker jobs without -P; LSF then charges them to this
# project. The driver job passes its environment on to the worker jobs.
export LSB_DEFAULTPROJECT="${CHARGE_CODE}"

# Workers are started as `volara-cli` from PATH, so the env with this repo
# installed must come first; otherwise they die on startup and daisy hangs.
NPS_ENV="/groups/troidl/home/troidlj/miniconda3/envs/nps"
export PATH="${NPS_ENV}/bin:${PATH}"

DATA_ROOT="/groups/troidl/troidllab/shape_reasoning"
LABEL_NAME="flywire_v141_initial"
SVID_NAME="ws_190410_FAFB_v02_ws_size_threshold_200"

CV_PATH="precomputed://file://${DATA_ROOT}/${LABEL_NAME}"
SVID_CV_PATH="precomputed://file://${DATA_ROOT}/${SVID_NAME}"
MIP=0
OUTPUT_DIR="${DATA_ROOT}/${LABEL_NAME}_points_v3"

# Workers are single-threaded (~0.7 s per 128^3 block), so scale by count:

NUM_WORKERS=64
CPUS_PER_WORKER=1
FRACTION=0.01

# Empty-block mask from an earlier scan (full volume, block size 128, mip 0).
# Reusing it skips the slow coarse-mip pre-scan; delete it to re-scan.
BLOCK_MASK="${DATA_ROOT}/${LABEL_NAME}_block_mask_bs128_mip0.npy"
MASK_ARGS=()
if [[ -f "${BLOCK_MASK}" ]]; then
    MASK_ARGS=(--block-mask "${BLOCK_MASK}")
fi

NPS_CMD=(nps --cv-path "${CV_PATH}"
    --svid-cv-path "${SVID_CV_PATH}"
    --mip "${MIP}"
    --fill-missing
    --output-dir "${OUTPUT_DIR}"
    --worker-type "${WORKER_TYPE}"
    --queue "${QUEUE}"
    --num-workers "${NUM_WORKERS}"
    --cpus-per-worker "${CPUS_PER_WORKER}"
    --fraction "${FRACTION}"
    "${MASK_ARGS[@]}")

# Every run re-samples all blocks, so points left over from an earlier run in
# the same directory would end up as duplicates.
if compgen -G "${OUTPUT_DIR}/points/worker_*" > /dev/null; then
    echo "ERROR: ${OUTPUT_DIR}/points already holds output of an earlier run." >&2
    echo "Delete it or change OUTPUT_DIR before starting a new run." >&2
    exit 1
fi

# Driver log goes to ./logs, worker logs to ./volara_logs (both relative to the
# directory this script is started from).
mkdir -p ./logs

if [[ "${WORKER_TYPE}" == "LSFWorker" ]]; then
    if ! command -v bsub > /dev/null; then
        echo "ERROR: bsub not found; run this from an LSF submit host." >&2
        exit 1
    fi
    # The driver only schedules blocks (and runs the pre-scan if no mask is
    # found); the block workers are separate LSF jobs.
    bsub -J "${RUN_NAME}" \
        -P "${CHARGE_CODE}" \
        -n 8 \
        -q "${QUEUE}" \
        -o "./logs/${RUN_NAME}.log" \
        "${NPS_CMD[@]}"
    echo "Submitted driver ${RUN_NAME}; follow it with: bjobs -w and tail -f ./logs/${RUN_NAME}.log"
else
    "${NPS_CMD[@]}" 2>&1 | tee "./logs/${RUN_NAME}.log"
fi
