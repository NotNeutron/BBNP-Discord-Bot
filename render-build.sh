#!/usr/bin/env bash
# exit on error
set -o errexit

STORAGE_DIR=$HOME/.local
mkdir -p $STORAGE_DIR

# Download ffmpeg static build
wget https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz

# Extract to storage directory
tar -xf ffmpeg-release-amd64-static.tar.xz -C $STORAGE_DIR --strip-components=1

# Clean up tarball
rm ffmpeg-release-amd64-static.tar.xz

# Install Python dependencies
pip install -r requirements.txt