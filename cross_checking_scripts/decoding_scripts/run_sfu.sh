#! /usr/bin/env bash

RUN="slurm" # "gnu_parallel" or "sequential" or "slurm"
INPUT_DIR="/data/datasets/MPEG-FCVCM/vcm_testdata" # needed for NN_PART2
BITSTREAM_DIR="/mnt/wekamount/scratch_fcvcm/eimran/runs/cfp_test" 

#################################################################
# CODEC_PARAMS="++pipeline.codec.encode_only=True" -> Only Encode
# CODEC_PARAMS="++pipeline.codec.decode_only=True" -> Only Decode
# CODEC_PARAMS="" -> Encode + Decode
CODEC_PARAMS="++pipeline.codec.decode_only=True" 
EXPERIMENT="_gen_bitstreams_v1"
QPS=`echo "8 12"`
DEVICE="cuda"
#################################################################

# total number of jobs = 84
if [[ ${RUN} == "gnu_parallel" ]]; then
    MAX_PARALLEL=84 
    run_scripts () {
        sem -j $MAX_PARALLEL bash $1
    }
    export -f run_scripts
elif [[ ${RUN} == "slurm" ]]; then
    run_scripts () {
        sbatch --gpus 1 --reservation=deepvideo --job-name=sfu_decode $1
    }
    export -f run_scripts
else
    run_scripts () {
        bash $1
    }
    export -f run_scripts
fi

for SEQ in \
            'Traffic_2560x1600_30_val' \
            'Kimono_1920x1080_24_val' \
            'ParkScene_1920x1080_24_val' \
            'Cactus_1920x1080_50_val' \
            'BasketballDrive_1920x1080_50_val' \
            'BQTerrace_1920x1080_60_val' \
            'BasketballDrill_832x480_50_val' \
            'BQMall_832x480_60_val' \
            'PartyScene_832x480_50_val' \
            'RaceHorses_832x480_30_val' \
            'BasketballPass_416x240_50_val' \
            'BQSquare_416x240_60_val' \
            'BlowingBubbles_416x240_50_val' \
            'RaceHorses_416x240_30_val'
do
    for QP in ${QPS}
    do
        echo RUN: ${RUN}, Input Dir: ${INPUT_DIR}, Bitstream Dir: ${BITSTREAM_DIR}, Exp Name: ${EXPERIMENT}, Device: ${DEVICE}, QP: ${QP}, SEQ: ${SEQ}, CODEC_PARAMS: ${CODEC_PARAMS}
        run_scripts "../mpeg_cfp_sfu.sh ${INPUT_DIR} ${BITSTREAM_DIR} ${EXPERIMENT} ${DEVICE} ${QP} ${SEQ} ${CODEC_PARAMS}"
    done
done

# GENERATE CSV
if [[ ${RUN} == "gnu_parallel" ]]; then
    sem --wait
    bash gen_csv.sh SFU ${BITSTREAM_DIR}/split-inference-video/cfp_codec${EXPERIMENT}/SFUHW/
elif [[ ${RUN} == "slurm" ]]; then
    sbatch --dependency=singleton --job-name=sfu_decode  gen_csv.sh SFU ${BITSTREAM_DIR}/split-inference-video/cfp_codec${EXPERIMENT}/SFUHW/
else
    bash gen_csv.sh SFU ${BITSTREAM_DIR}/split-inference-video/cfp_codec${EXPERIMENT}/SFUHW/
fi


