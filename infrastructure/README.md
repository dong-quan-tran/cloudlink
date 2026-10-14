# Infrastructure Status

## Environment
- AWS Academy Cloud Architecting Sandbox.
- Region: us-east-1.
- Session timer: 3 hours.
- Resource persistence: not confirmed.
- IAM: read-only.

## Network
- VPC: 10.20.0.0/16.
- Source subnet: 10.20.1.0/24.
- Destination subnet: 10.20.2.0/24.
- Internet gateway attached.
- Both subnets use the public route table.
- Resource IDs are saved in network.json.

## Servers
| Role | Instance ID | Private IP |
|---|---|---|
| Source | i-0e4cb59f00340b267 | 10.20.1.33 |
| Destination | i-0f32c4732129523c5 | 10.20.2.151 |

Both servers were running at the last verified test.
SSH access worked for both.

## Security rules
- SSH port 22 allowed from Johnny's public IP at setup time.
- Destination TCP port 8000 allowed from the source security group.

## Test service
- Destination service: cloudlink-test.
- Port: 8000.
- Setup script: setup-destination.sh.
- Healthy response: CloudLink destination is healthy.

## Verified result
The source reached http://10.20.2.151:8000/.
No controlled failure tests have been run yet.

## Remaining work
- Run and document failure tests.
- Verify recovery after each test.
- Finish repeatable network setup and cleanup.
- Confirm sandbox persistence and shared access.
- Help Joel test the app.

## Credentials
Keep credentials and SSH keys outside the repository.
Local CLI credentials must be refreshed when expired or in a new terminal.
