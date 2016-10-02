#!/bin/bash

# Test sharing for sheet_name = ex-adminpaced | ex-team
#
# Usage: adminpaced.sh sheet_name    (compile only)
#        adminpaced.sh -r sheet_name (compile and run)
#        adminpaced.sh -d target message (send direct message only)

PORT=8081
SHEET_URL=https://script.google.com/macros/s/AKfycbxCAcduzxE_2EWePkpKROCRPiQtXTXQeqtW3SOhX2evubaLErE/exec
SHEET_KEY=testkey
TEST_SCRIPT=basic
PROXY_URL=http://localhost:$PORT/_proxy

TWSTREAM1='slidocu,m7xDX9qWSkwQReDdByTuJnVkx,PtGWGnjV5PXcGMxjhfSaUv7etHGGIzMXOp0FA42hA06SkfmHSX,777730855938629635-kY8wnGB5Z7E03yq4xbNF7ED1dX1BQd7,44FFA1d6HlPPxMv41FKAL0AXTOEQUoNmvlUm4DCwDrR64'

TWSTREAM1=

TWSTREAM2='geos210,pipTR8H00rmLzQaIMOI2OuJeB,QoFIHU2aNAv0HQ7pCIBIjOQU4kPkveHVU2TDLl7cx5sdwHIhSx,770391997051908096-k2uZJRya28XNAaNlbJBINMp7FXwIDBm,Bp8fv39LbF73KupmuufmvBrR2WmiN4d5WCCuvFvokqIbB'

run=0
if [ $# -ge 1 ]; then

    if [ "$1" == "-d" ]; then
        sdstream.py --twitter_stream=$TWSTREAM2 --dm $*
        exit 0
    fi
    if [ "$1" == "-r" ]; then
        run=1
        shift
	curl "http://localhost:${PORT}/_shutdown?token=${SHEET_KEY}"
        sleep 2

        cmd="sdserver.py --auth_key=$SHEET_KEY --twitter_stream=$TWSTREAM1 --static_dir=. --proxy_wait=0 --port=$PORT --no_auth --debug"
        echo $cmd
        $cmd &

        sleep 5
    fi
fi

if [ $# -lt 1 ]; then
    echo "Usage: adminpaced.sh [-r] sheet_name"
    exit 1
fi

SHEET_NAME=$1

slidoc.py --pace=3 --remote_logging=2 --auth_key=$SHEET_KEY --gsheet_url=$PROXY_URL --proxy_url=/_websocket --test_script=1 --debug ${SHEET_NAME}.md

if [ $run -gt 0 ]; then
   users=(_test_user bbb ccc)
   browsers=(Safari 'Google Chrome' Firefox)

   for i in 0 1 2; do
       echo open -a "${browsers[$i]}" "http://localhost:${PORT}/_auth/login/?username=${users[$i]}&token=${SHEET_KEY}&next=/${SHEET_NAME}.html%3Ftestscript%3D${users[$i]}%26testuser%3D${users[$i]}%26testkey%3D${SHEET_KEY}"
       open -a "${browsers[$i]}" "http://localhost:${PORT}/_auth/login/?username=${users[$i]}&token=${SHEET_KEY}&next=/${SHEET_NAME}.html%3Ftestscript%3D${users[$i]}%26testuser%3D${users[$i]}%26testkey%3D${SHEET_KEY}"
   done
fi
