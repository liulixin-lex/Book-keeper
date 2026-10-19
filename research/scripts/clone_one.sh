#!/bin/bash
# usage: clone_one.sh <category> <owner/repo> [sparse,paths]
set -u
root=/Users/admin/XIN-MAC-XN/bookkeeper-rebuild/research/repos
cat=$1; repo=$2; sparse=${3:-}; [ "$sparse" = "-" ] && sparse=""
dest="$root/$cat/${repo/\//__}"
[ -d "$dest/.git" ] && { echo "SKIP $repo"; exit 0; }
mkdir -p "$root/$cat"
export GIT_LFS_SKIP_SMUDGE=1 GIT_TERMINAL_PROMPT=0
if [ -n "$sparse" ]; then
  git clone -q --depth 1 --filter=blob:none --sparse "https://github.com/$repo.git" "$dest" 2>>"$root/../clone_errors.log" \
    && git -C "$dest" sparse-checkout set ${sparse//,/ } 2>>"$root/../clone_errors.log" \
    && echo "OK(sparse) $repo" || echo "FAIL $repo"
else
  git clone -q --depth 1 "https://github.com/$repo.git" "$dest" 2>>"$root/../clone_errors.log" && echo "OK $repo" || echo "FAIL $repo"
fi
