#!/bin/bash
# The main hub: one server for every project under the factory root (portal at /, hubs at /p/<slug>/).
# Runs the code of the checkout this script is in, against <repo>/data (or $FACTORY_DATA).
# Usage: scripts/hub.sh [--port N] [--no-feed]   (options go to `factory site serve --all`)
set -e
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
MAIN=$(cd "$(git -C "$HERE" rev-parse --git-common-dir)/.." && pwd)   # the repo, from any worktree
export PYTHONPATH=$HERE/platform/src
export FACTORY_ROOT=${FACTORY_DATA:-$MAIN/data}
export FACTORY_PLUGIN_DIR=$HERE/plugin
unset FACTORY_PROJECT
exec "$MAIN/platform/.venv/bin/python" -c "from factory.cli.main import app; app()" site serve --all "$@"
