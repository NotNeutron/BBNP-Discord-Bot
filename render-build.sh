#!/usr/bin/env bash
set -o errexit

STORAGE_DIR=$HOME/.local
mkdir -p $STORAGE_DIR

wget https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz

tar -xf ffmpeg-release-amd64-static.tar.xz -C $STORAGE_DIR --strip-components=1

rm ffmpeg-release-amd64-static.tar.xz

pip install -r requirements.txt
