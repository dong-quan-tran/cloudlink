# Controlled Test Scenarios

All scenarios are planned, not yet executed.

| ID | Scenario | Change | Expected result | Status |
|---|---|---|---|---|
| T01 | Healthy baseline | Service running; intended traffic allowed | TCP connection succeeds | Not run |
| T02 | Blocked port | Remove destination permission for port 8000 | Probe fails; configuration check flags missing permission | Not run |
| T03 | Wrong source range | Replace matching source range with a nonmatching range | Probe fails; configuration check flags mismatch | Not run |
| T04 | Service stopped | Stop destination service | Probe fails; avoid claiming a confirmed cloud-network blocker | Not run |
| T05 | Instance stopped | Stop destination instance | Report destination not running | Not run |
| T06 | Restored baseline | Undo the previous change | TCP connection succeeds again | Not run |

## Procedure
1. Confirm the healthy baseline.
2. Record the settings before the change.
3. Introduce exactly one failure.
4. Run the test.
5. Save the result and evidence.
6. Restore the original settings.
7. Verify the healthy connection again.

## Record for each test
- Date/time:
- Scenario ID:
- Source instance:
- Destination instance:
- Destination private IP:
- Port:
- Exact change:
- Expected result:
- Actual result:
- Evidence:
- Restoration steps:
- Baseline restored:
