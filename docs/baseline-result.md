# Healthy Baseline — T01

## Result
PASS: The source server reached the destination test service.

## Environment
- Region: us-east-1
- Source instance: i-0e4cb59f00340b267
- Source private IP: 10.20.1.33
- Destination instance: i-0f32c4732129523c5
- Destination private IP: 10.20.2.151
- Protocol: HTTP over TCP
- Destination port: 8000

## Test
Executed on the source server:

curl --fail --connect-timeout 5 --max-time 10 http://10.20.2.151:8000/

## Actual response
CloudLink destination is healthy

## What this confirms
The tested source-to-destination connection works.
The destination HTTP service responds on port 8000.

## Destination service
- Service name: cloudlink-test
- Setup script: infrastructure/setup-destination.sh
- Start: sudo systemctl start cloudlink-test
- Stop: sudo systemctl stop cloudlink-test
- Status: sudo systemctl status cloudlink-test

## Next test
Stop the destination service, verify the connection fails,
then restart it and verify the baseline returns.
