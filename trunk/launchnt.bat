@echo Starting a DAQ run under Windows NT
@SET CONFIGDIR=..\config
@SET LOGADDR=localhost:9001

@echo Starting Pythonic glue processes ...
@start "DAQ-RUN" DAQRun.py -c %CONFIGDIR% -l ..\log -n
@start "CNC-SERVER" CnCServer.py -l %LOGADDR%

@echo Bringing up the DAQ components ...

@echo #1 - EventBuilder ...
@start "EVENT-BUILDER" java icecube.daq.eventBuilder.EBComponent -g %CONFIGDIR% -l %LOGADDR%
@sleep 1

@echo #2 - Triggers
@start "GLOBAL TRIGGER" java icecube.daq.trigger.component.GlobalTriggerComponent -g %CONFIGDIR% -l %LOGADDR%
@start "INICE TRIGGER" java icecube.daq.trigger.component.IniceTriggerComponent -g %CONFIGDIR% -l %LOGADDR%
@sleep 1

@echo #3 - StringHub
@start "STRINGHUB-1001" java -Dicecube.daq.stringhub.simulation=true -Dicecube.daq.stringhub.componentId=1001 icecube.daq.stringhub.Shell -g %CONFIGDIR% -l %LOGADDR%
