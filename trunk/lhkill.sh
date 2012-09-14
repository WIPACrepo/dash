#!/usr/bin/env bash

# Detect "java-only" option
while getopts :j FLAG; do
   case "${FLAG}" in
      j) JAVA_ONLY=on
         ;;
   esac
done

hn=`hostname`
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

echo "Node $hn:"

if [ -z "$JAVA_ONLY" ] 
then
   echo -n "Killing servers... "
   $dash/CnCServer.py -k
   $dash/DAQRun.py    -k
fi

echo -n "Killing Java pDAQ components... "
comp_classes_regexp="icecube.daq.juggler.toybox.DAQCompApp|\
icecube.daq.eventBuilder.EBComponent|\
icecube.daq.secBuilder.SBComponent|\
icecube.daq.trigger.component.IniceTriggerComponent|\
icecube.daq.trigger.component.GlobalTriggerComponent|\
icecube.daq.stringhub"
pkill -fu ${USER} ${comp_classes_regexp}
echo -n "Waiting for components to die... "
sleep 2
stragglers=$(pgrep -fu ${USER} ${comp_classes_regexp})
if [ -n "${stragglers}" ]; then
  echo -n "Killing with -9... "
  pkill -9 -fu ${USER} ${comp_classes_regexp}
fi
echo "OK"
echo " "
