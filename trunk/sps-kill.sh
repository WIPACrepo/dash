#!/usr/bin/env bash

# Functions for parallelizing:
fileKey="sps-kill"
function atexit () {  # Trick borrowed from Arthur - clean up tmp files
    rm -f /tmp/${fileKey}.$$.*;
}
trap atexit EXIT

function waitpids() {
   for pid in $1; do
      wait ${pid}
   done
}

function showResults() {
   for n in $@; do
      cat /tmp/${fileKey}.$$.$n
   done
}

# find the location of the standard directories
#
for loc in '..' '.'; do
    if [ -d "$loc/config" -a -d "$loc/trigger" -a -d "$loc/dash" ]; then
        topdir="$loc"

	# find standard scripts
	#
	if [ "$loc" = "." ]; then
	    dash='dash'
	else
	    if [ -f lhkill.sh ]; then
	        dash='.'
	    else
	        dash="$loc/dash"
	    fi
	fi
    fi
done

$dash/lhkill.sh

echo "Killing java components on remote nodes:"
NODES="sps-2ndbuild sps-evbuilder sps-gtrigger sps-iitrigger "
NODES=$NODES" sps-ichub21 sps-ichub29 sps-ichub30 sps-ichub39"

for node in $NODES; do
   (ssh $node "cd pDAQ_trunk; ./dash/lhkill.sh -j") 2>&1 > /tmp/${fileKey}.$$.$node &
   pids="$pids $!"
done

waitpids $pids
sleep 2 # Wait for final file output to get flushed - this is kludgy but works on SPS
showResults $NODES

echo "Done."
