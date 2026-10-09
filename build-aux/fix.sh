#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# Runs every formatter, then ruff's safe fixes: `meson compile -C build fix`.
# Meson passes the tools it found; ruff's exit status reports what's left.
set -eu
ruff=$1
blueprint_compiler=$2
meson=$3
cd "$MESON_SOURCE_ROOT"
"$ruff" format .
find src -name '*.blp' -exec "$blueprint_compiler" format --fix --no-diff {} +
"$meson" format --inplace --recursive .
"$ruff" check --fix .
