#!/bin/bash

cfg='../config'
log='../log'
spade='../spade'

./lhkill.sh

echo "Cleaning up logs..."

if ! [ -e $spade ]
then
    mkdir $spade
else
    rm -rf $spade/*
fi

if ! [ -e $log ]
then 
    mkdir $log 
else 
    rm -rf $log/catchall.log $log/daqrun* $log/old_daqrun*
fi

echo "Starting DAQRun..."
./DAQRun.py -c $cfg -l $log -s $spade

echo "Starting CnCserver..."
./CnCServer.py -d -l localhost:9001

startComponent () {
    dir=$1
    scr=$2
    out=$3
    id=$4
    if [ $out = 1 ]
    then
	(cd ../$dir; ./$scr $id -g $cfg -l localhost:9001 &) &
    else
	(cd ../$dir; ./$scr $id -g $cfg -l localhost:9001 1>/dev/null 2> /dev/null &) &
    fi
}

echo "Starting eventbuilder..."
startComponent eventBuilder-prod run-eb 0

echo "Starting global trigger..."
startComponent trigger run-gltrig 0

echo "Starting in-ice trigger..."
startComponent trigger run-iitrig 0

echo "Starting StringHub..."
startComponent StringHub run-hub 0 1001

echo "Done."
echo "Type './ExpControlSkel.py' to run the test."
echo "Results will appear in $log."


