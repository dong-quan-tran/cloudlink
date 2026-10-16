# AWS Academy lab deployment

The network template explicitly places all three lab subnets in `us-east-1a` by default. This avoids an automatic placement in a zone that cannot launch `t3.micro`, such as `us-east-1e` in this sandbox. This is a single-zone lab with separate public and private subnets, not a high-availability deployment. For manual uploads, choose `AvailabilityZone` when creating the **network** stack; EC2 inherits its subnet's zone. For the script, use `--availability-zone us-east-1b` to choose another supported zone. If you change `--region`, also select a zone in that region that supports `t3.micro`.

If an existing subnet was created in an unsupported zone, recreate the disposable lab before using the updated network template. In CloudFormation, delete `cloudlink-probes` if present, then the failed `cloudlink-web` stack, then `cloudlink-network`, waiting for each deletion to finish. Recreate network → web → probes in that order, or rerun the deployment script. Deleting the web stack removes its instance and local SQLite history. Changing a subnet's zone requires replacement; an in-place network update with the same CIDR ranges is not a supported migration. The script does not delete stacks for you.

Run this from a fresh AWS Academy CloudShell session in `us-east-1`:

```bash
git clone https://github.com/dong-quan-tran/cloudlink.git
cd cloudlink
bash scripts/deploy-sandbox.sh --management-cidr YOUR_COMPUTER_PUBLIC_IP/32
```

If the repository is already in CloudShell, run `git pull --ff-only` inside it before the script. You can omit `--management-cidr` and enter the address when prompted. Use the public IPv4 address of **your computer's internet connection**, not the address printed by CloudShell. The `/32` restricts administrative SSH to the web instance. The script checks for AWS access and the Academy `vockey` key pair, validates the three templates, then creates or updates `cloudlink-network`, `cloudlink-web`, and `cloudlink-probes` in dependency order. It prints the current web URL at the end; the instance's public IP may change when recreated.

The network stack gives only the web subnet an internet-gateway route. Probe A and B have separate private subnets and route tables with the VPC-local route only; newly launched probes receive no public IP. CloudLink reaches a selected probe over private SSH, and the probe tests the other node's private IP. The probes download their CloudLink management public key from the web instance over the VPC-local path, so they do not need a NAT gateway during bootstrap. Direct SSH from your computer to a probe is not available in this layout.

The demo dashboard is publicly reachable over unauthenticated HTTP port 80 by default. Do not use real credentials, private data, or production resources in this lab. The app reads its own lab inventory and does not need sandbox credentials pasted into its UI.

By default, ICMP and TCP port 8080 are allowed between the two probe nodes. Peer-to-peer SSH remains blocked, so an SSH banner test should fail even when ping succeeds. To allow the SSH banner test too, rerun with `--enable-peer-ssh`; this adds TCP 22 rules only between the two probe security groups. It does not make port 22 publicly accessible.

Subnet public-IP settings affect new instances only. If you rerun the script against an older deployment whose probes already have public IPs, it warns you; it does not replace those instances automatically. A fresh sandbox deployment gets private probes from the start.

The web application is installed from the selected repository ref only when the web EC2 instance is first created. Updating an existing CloudFormation stack does not automatically reinstall newer application code on that instance.
