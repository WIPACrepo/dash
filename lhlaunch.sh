#!/bin/bash

# check command-line options
#
if [ "$1" = "bfd" ]; then
    ignore_mvn=true
fi

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

# set standard directories
#
cfg="$topdir/config"
log="$topdir/log"
spade="$topdir/spade"

mvn_subdir='target/classes'

$dash/lhkill.sh

echo "Cleaning up logs..."

if ! [ -e $spade ]
then
    mkdir $spade
fi

if ! [ -e "$log" ]
then 
    mkdir $log
else 
    rm -rf $log/catchall.log $log/daqrun* $log/old_daqrun*
fi

echo "Starting DAQRun..."
$dash/DAQRun.py -c $cfg -l $log -s $spade

echo "Starting CnCserver..."
$dash/CnCServer.py -d -l localhost:9001

startComponent () {
    nam=$1
    dir=$2
    scr=$3
    out=$4
    id=$5
    if [ -z "$ignore_mvn" -a -f "$topdir/$dir/$mvn_subdir/$scr" ]; then
        prog="$mvn_subdir/$scr"
    else
        if [ -f "$topdir/$dir/$scr" ]; then
	    prog="$scr"
	else
	    prog=''
	fi
    fi

    if [ -z "$prog" ]; then
        echo "$0: Couldn't find $nam script $scr" >&2 
    else
        echo "Starting $nam..."
        if [ $out = 1 ]; then
	    (cd $topdir/$dir; sh $prog $id -g $cfg -l localhost:9001 &) &
        else
            (cd $topdir/$dir; sh $prog $id -g $cfg -l localhost:9001 1>/dev/null 2> /dev/null &) &
	fi
    fi
}

startComponent 'event builder' eventBuilder-prod run-eb 0

startComponent 'global trigger' trigger run-gltrig 0

startComponent 'in-ice trigger' trigger run-iitrig 0

startComponent 'string hub' StringHub run-hub 0 1001

echo ""
echo "Type '$dash/ExpControlSkel.py' to run the test."
echo "Results will appear in $log."
