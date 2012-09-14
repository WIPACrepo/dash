#!/usr/bin/env bash

# check command-line options
#
if [ "$1" = "bfd" ]; then
    imvn="--ignore-maven"
fi

# Uncomment the following if you want verbose info at stdout/stderr:
# verbose="--verbose" 

# find the location of the standard directories
#
for loc in '..' '.'; do
    if [ -d "$loc/config" -a -d "$loc/trigger" -a -d "$loc/dash" ]; then
        topdir=`cd "$loc" && pwd`

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
if [ -d /mnt/data/spade/pdaq/runs ]; then
    spade="/mnt/data/spade/pdaq/runs"
else
    spade="$topdir/spade"
fi

mvn_subdir='target/classes'

$dash/sps-kill.sh

echo "Cleaning up logs..."

if ! [ -e $spade ]
then
    mkdir $spade
fi

if ! [ -e "$log" ]
then 
    mkdir $log
else 
    rm -rf $log/catchall.log 
fi

echo "Starting DAQRun..."
if [ -z "$verbose" ]
then
    $dash/DAQRun.py -c $cfg -l $log -s $spade
else
    $dash/DAQRun.py -c $cfg -l $log -s $spade -n &
fi

echo "Starting CnCserver..."
if [ -z "$verbose" ]
then
    $dash/CnCServer.py -d -l localhost:9001
else
    $dash/CnCServer.py -l localhost:9001 &
fi

ssh sps-2ndbuild  "cd pDAQ_trunk; ./dash/StartComponent.py -c secondaryBuilders -s run-sb     --cnc sps-expcont:8080 --log sps-expcont:9001 $imvn $verbose"
ssh sps-evbuilder "cd pDAQ_trunk; ./dash/StartComponent.py -c eventBuilder-prod -s run-eb     --cnc sps-expcont:8080 --log sps-expcont:9001 $imvn $verbose"
ssh sps-gtrigger  "cd pDAQ_trunk; ./dash/StartComponent.py -c trigger           -s run-gltrig --cnc sps-expcont:8080 --log sps-expcont:9001 $imvn $verbose"
ssh sps-iitrigger "cd pDAQ_trunk; ./dash/StartComponent.py -c trigger           -s run-iitrig --cnc sps-expcont:8080 --log sps-expcont:9001 $imvn $verbose"

echo "cd pDAQ_trunk; ./dash/StartComponent.py -c StringHub         -s run-hub    --cnc sps-expcont:8080 --log sps-expcont:9001 --id 1001 $imvn $verbose" | ssh -T sps-ichub21
echo "cd pDAQ_trunk; ./dash/StartComponent.py -c StringHub         -s run-hub    --cnc sps-expcont:8080 --log sps-expcont:9001 --id 1002 $imvn $verbose" | ssh -T sps-ichub29
echo "cd pDAQ_trunk; ./dash/StartComponent.py -c StringHub         -s run-hub    --cnc sps-expcont:8080 --log sps-expcont:9001 --id 1003 $imvn $verbose" | ssh -T sps-ichub30
echo "cd pDAQ_trunk; ./dash/StartComponent.py -c StringHub         -s run-hub    --cnc sps-expcont:8080 --log sps-expcont:9001 --id 1004 $imvn $verbose" | ssh -T sps-ichub39
#echo "cd pDAQ_trunk; ./dash/StartComponent.py -c StringHub         -s run-hub    --cnc sps-expcont:8080 --log sps-expcont:9001 --id 1038 $imvn $verbose" | ssh -T sps-ichub38

echo ""
echo "Type '$dash/ExpControlSkel.py' to run the test."
echo "Results will appear in $log."
