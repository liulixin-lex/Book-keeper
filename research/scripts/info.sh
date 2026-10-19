#!/bin/bash
# usage: info.sh <repo_dir>  — prints license, size, file mix, top-level tree
d=$1
echo "## $(basename $d)"
lic=$(ls $d | grep -iE '^(license|licence|copying)' | head -1)
[ -n "$lic" ] && echo "license: $(grep -m3 -iE 'license|GPL|MIT|Apache|BSD|MPL|AGPL' $d/$lic | head -2 | tr -s ' ' | cut -c1-120 | tr '\n' ' ')"
echo "size: $(du -sh $d 2>/dev/null | cut -f1)  files: $(git -C $d ls-files | wc -l)"
echo "ext: $(git -C $d ls-files | sed -n 's/.*\.\([a-zA-Z0-9]*\)$/\1/p' | sort | uniq -c | sort -rn | head -8 | awk '{printf "%s:%s ",$2,$1}')"
echo "last commit: $(git -C $d log -1 --format='%cs %h %s' | cut -c1-100)"
echo "tree:"; (cd $d && ls -1 | head -40 | tr '\n' ' '); echo
