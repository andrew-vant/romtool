#!/bin/bash
# shellcheck disable=SC2059

# take roms as args and loop on them
# use tmpdir for dump/load
# rmdir tmpdir afterward if possible
# printf can be once per cmd rather than once per line
# alternately printf to var
set -e

function mytime () { /usr/bin/time -f %e "$@" |& tr -d '\n'; }
# function mytime () { echo /usr/bin/time -f %e "$@" ; }

function main()
{
	fmt="%-18s"
	tmpdir=/tmp/rt.perftest
	revs=$(git rev-list --reverse "$1")
	shift

	# Print header
	printf "$fmt" commit
	for rom in "$@"; do
		for cmd in dump build; do
			name=$(basename "$rom")
			name=${name%%.*}
			printf "$fmt" "${cmd}-${name}"
		done
	done
	echo commit-message

	# main loop
	for rev in $revs; do
		git checkout -q "$rev"
		printf "$fmt" "$(git log -n 1 --pretty=format:%h)"
		for rom in "$@"; do
			rm -rf "$tmpdir"
			mkdir -p "$tmpdir"
			printf "$fmt" "$(mytime romtool dump -fq "$rom" "$tmpdir")s"
			printf "$fmt" "$(mytime romtool build -fqo "$tmpdir"/patch.ipst "$rom" "$tmpdir")s"
		done
		printf "%s\n" "$(git log -n 1 --pretty=format:%s)"
	done
}

main "$@"
