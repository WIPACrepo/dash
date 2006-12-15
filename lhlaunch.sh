#!/bin/bash

wd=`pwd`
cfg=$wd'/../config'
log=$wd'/../log'

echo "Killing existing components..."
./CnCServer.py -k
./DAQRun.py    -k 

ps ax | egrep 'java icecube.daq.juggler.toybox.DAQCompApp' | grep -v grep | awk '{print $1}' | xargs kill -9
ps ax | egrep 'java icecube.daq.eventBuilder.EBComponent'  | grep -v grep | awk '{print $1}' | xargs kill -9
ps ax | egrep 'java -Dicecube.daq.stringhub'               | grep -v grep | awk '{print $1}' | xargs kill -9

echo "Cleaning up logs..."

if ! [ -e $log ]
then 
    mkdir $log 
else 
    rm -rf $log/catchall.log $log/daqrun* $log/old_daqrun*
fi

echo "Starting DAQRun..."
./DAQRun.py -c $cfg -l $log

echo "Starting CnCserver..."
./CnCServer.py -d

echo "Starting 'zero' component..."
(cd ../juggler; ./run-comp -l localhost:9001 zero 2>/dev/null &) &

echo "Starting event builder harness component..."
(cd ../juggler; ./run-comp -l localhost:9001 ebHarness 2>/dev/null &) &

echo "Starting eventbuilder..."
(cd ../eventBuilder-prod; ./run-eb -l localhost:9001 2>/dev/null &) &

echo "Starting StringHub..."
(cd ../StringHub; ./run-hub 1001 -l localhost:9001 1>/dev/null 2>/dev/null &) &

echo "Done."
echo "Type './ExpControlSkel.py' to run the test."
echo "Results will appear in $log."


