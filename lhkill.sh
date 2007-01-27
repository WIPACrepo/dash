#!/usr/bin/env bash

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
comp_classes_regexp="icecube.daq.juggler.toybox.DAQCompApp|\
icecube.daq.eventBuilder.EBComponent|\
icecube.daq.secBuilder.SBComponent|\
icecube.daq.trigger.component.IniceTriggerComponent|\
icecube.daq.trigger.component.GlobalTriggerComponent|\
icecube.daq.stringhub"
pkill -fu ${USER} ${comp_classes_regexp}
echo "Waiting for components to die..."
sleep 2
stragglers=$(pgrep -fu ${USER} ${comp_classes_regexp})
if [ -n "${stragglers}" ]; then
  echo "Killing with -9..."
  pkill -9 -fu ${USER} ${comp_classes_regexp}
fi
