#!/usr/bin/env bash
cd "$(dirname "$0")"
echo "Installing dependencies..."
pip install -r requirements.txt
echo "Starting Python Local Server on http://localhost:5000 ..."
python server.py
