#!/bin/sh
#SBATCH --partition=GPUQ
#SBATCH --time=10:00:00
#SBATCH --job-name="dialog-dicriminator-memory-profile"
#SBATCH --account=share-ie-idi
#SBATCH --nodes=1
#SBATCH --gres=gpu
#SBATCH --mem=32G
#SBATCH --constraint=gpu16g
#SBATCH --output=mem_profile.txt

module load Python/3.9.6-GCCcore-11.2.0
module load CUDA/11.8.0
source .venv/bin/activate
python memory_profiling.py