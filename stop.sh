#!/bin/bash
set -e

cd "$(dirname "$0")"

echo "Stopping AIScoutBot..."
docker compose down

echo "Done."
