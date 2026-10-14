# CloudLink Infrastructure

## Environment
- AWS Academy Cloud Architecting Sandbox
- Region: us-east-1
- Session timer: 3 hours
- Resource persistence: not confirmed
- IAM access: read-only

## Network created
- VPC: 10.20.0.0/16
- Source subnet: 10.20.1.0/24
- Destination subnet: 10.20.2.0/24

Resource IDs are in network.json.

## Planned servers
- Source: runs the connection probe.
- Destination: runs a test service on TCP port 8000.
- Test traffic will use the destination's private IP.

## Remaining work
1. Configure internet access needed for server setup and SSH.
2. Create separate source and destination security groups.
3. Launch two permitted Amazon Linux instances.
4. Start the destination service.
5. Verify the healthy connection.
6. Test one failure at a time and restore the baseline.

## Session access
CLI credentials are entered into the local terminal.
Refresh them when they expire or when opening a new terminal.
Do not save them in this repository.
