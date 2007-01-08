#!/bin/bash

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

echo "Killing servers..."
$dash/CnCServer.py -k
$dash/DAQRun.py    -k 

echo "Killing components..."
for class in \
        icecube.daq.juggler.toybox.DAQCompApp \
        icecube.daq.eventBuilder.EBComponent \
        icecube.daq.trigger.component.IniceTriggerComponent \
        icecube.daq.trigger.component.GlobalTriggerComponent \
        icecube.daq.stringhub
do
    for p in `ps axww | grep "java .*$class" | grep -v grep | awk '{print $1}'`
    do
        kill -9 $p
    done
done
