# AWS Academy lab deployment

Run this from a fresh AWS Academy CloudShell session in `us-east-1`:

```bash
git clone https://github.com/dong-quan-tran/cloudlink.git
cd cloudlink
bash scripts/deploy-sandbox.sh --management-cidr YOUR_COMPUTER_PUBLIC_IP/32
```

If the repository is already in CloudShell, run `git pull --ff-only` inside it before the script. You can omit `--management-cidr` and enter the address when prompted. Use the public IPv4 address of **your computer's internet connection**, not the address printed by CloudShell. The `/32` restricts administrative SSH to that one address. The script checks for AWS access and the Academy `vockey` key pair, validates the three templates, then creates or updates `cloudlink-network`, `cloudlink-web`, and `cloudlink-probes` in dependency order. It prints the current web URL at the end; the instance's public IP may change when recreated.

The demo dashboard is publicly reachable over unauthenticated HTTP port 80 by default. Do not use real credentials, private data, or production resources in this lab. The app reads its own lab inventory and does not need sandbox credentials pasted into its UI.

By default, ICMP and TCP port 8080 are allowed between the two probe nodes. Peer-to-peer SSH remains blocked, so an SSH banner test should fail even when ping succeeds. To allow the SSH banner test too, rerun with `--enable-peer-ssh`; this adds TCP 22 rules only between the two probe security groups. It does not make port 22 publicly accessible.

The web application is installed from the selected repository ref only when the web EC2 instance is first created. Updating an existing CloudFormation stack does not automatically reinstall newer application code on that instance.
