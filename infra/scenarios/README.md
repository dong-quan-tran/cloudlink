# Network scenarios

Five standalone templates. Adds test probes without changing app code or existing templates.

Requires CloudLink already deployed from current `main` in your personal account, `us-east-1`.
Uses its network exports, app security group, and shared probe SSH key. No PEM upload needed.

## Run

From the repo folder in CloudShell, choose one:

```bash
bash infra/scenarios/deploy.sh private-subnets
```

Replace `private-subnets` with any name below. Only one scenario runs at a time.
Choosing another **deletes the previous scenario stack** before deploying the new one.
Re-running the same scenario updates it.

Refresh CloudLink's probe list. Choose the two nodes named `CloudLink-<scenario>-A/B`.
Use **private IP**, **Ping**, and **Custom TCP: 8080**. Test both directions.

| Scenario / template name | Ping A→B / B→A | TCP 8080 A→B / B→A | Cause |
|---|---|---|---|
| `private-subnets` | Pass / Pass | Pass / Pass | Two subnets, one VPC |
| `sg-block-8080` | Pass / Pass | Fail / Pass | B has no inbound 8080 allow rule from A |
| `nacl-block-8080` | Pass / Pass | Fail / Pass | B's subnet ACL denies inbound 8080 from A before its allow rule |
| `peering-working` | Pass / Pass | Pass / Pass | Two VPCs, direct peering, routes both ways |
| `peering-missing-route` | Fail / Fail | Fail / Fail | B has no route to A's VPC; A's forward route remains |

CloudLink's management SSH to **either** probe should work in every scenario.
Probe-to-probe SSH, HTTP 80, and HTTPS 443 should fail, as in main.
The helper prints expected results; run the website tests to verify them.

## What gets added

- Dedicated stack: `cloudlink-scenario`; two private `t3.micro` AL2023 probes, standard CPU credits, 8 GiB gp3 each.
- Same TCP 8080 service and discovery tags as main; scenario names keep them separate from the original probes.
- Scenario VPCs: `10.60.0.0/16`, plus `10.61.0.0/16` for peering cases. They must not overlap your other networks.
- Direct management peering to the app VPC (`10.20.0.0/16`), routes in both existing app route tables, and separate SSH rules.
- No public IPs, NAT gateways, extra app servers, or app changes. Existing main probes stay running.

The missing data route does not affect management SSH. The ACL fault targets only A→B TCP 8080.
Both scenario probes use the same AZ. AWS assigns their private IPs; use the printed outputs.

## Remove

```bash
bash infra/scenarios/deploy.sh delete
```

This removes the scenario probes, VPCs, peering, and added app routes. Delete it **before** running the main teardown.
It keeps the existing app, original probes, shared key, and history. Running instances and disks incur charges until removed.

For direct CloudFormation deployment, each `.yaml` also works alone. Supply `AppRouteTableAId` and
`AppRouteTableBId` from the `cloudlink-network` resources `AppRoutesA/B`. The helper finds these for you.
Use the helper for switching and cleanup; it checks the stack's `ManagedBy=CloudLinkScenarios` and `Project=CloudLink` tags.
