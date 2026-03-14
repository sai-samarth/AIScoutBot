#!/bin/bash
set -e

cd "$(dirname "$0")"

if [[ "$1" == "--rebuild" ]]; then
  echo "Building and starting AIScoutBot..."
  docker compose up -d --build
else
  echo "Starting AIScoutBot..."
  docker compose up -d
fi

echo ""
docker compose ps
