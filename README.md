# ghr-smoke

Smoke-test consumer for azure-gh-runners. This public repository accepts no
pull-request-triggered self-hosted work.

## Code-only VMSS preparation

`.github/workflows/vmss-smoke.yml` is a proposed manual allow workflow, not
runtime acceptance or authorization to dispatch. Keep its preparation PR draft
and **do not merge** until separately reviewed. No runtime has been performed.

The hosted validation job checks the owner actor, exact repository/main workflow
ref, immutable reviewed commit (both workflow SHA and job SHA), original
32-lowercase-hex envelope, ordinal `1` or `2`, exact label, isolated resource
group expectation before a worker is queued.
The agreed custom-only label is
`ghr-smoke-vmss-spike-<32-lowercase-hex-envelope>-<ordinal>`.
There are no actions, checkout, secrets, GitHub OIDC requests, or requested
token permissions. The worker job has a 15-minute limit; registry retention
remains the parent's unchanged 360-minute policy.

Each ordinal is one FULL run with one nonroot worker and no intra-run retries.
Workflow reruns (`GITHUB_RUN_ATTEMPT` other than `1`) are rejected.
The parent must durably reserve each ordinal once, verify ALL cleanup including
owner spike-key revocation before the second run, and retain the SAME original
four-hour/$10 envelope. Workflow concurrency is only serialization, not a
durable replay/budget guard; a queued job's timeout is not a substitute for
controller expiry/cancellation/cleanup.

Worker assertions require uid/gid 1001, absent sudo executable and Docker
daemon/socket, immutable rootowned verifier/manifest/hook files, the actual
spike hook, and `/bin/bash /opt/ghr-vmss/verify-spike-worker.sh` for manifest-pinned
tools and spike posture checks. The hook environment is never overridden and
the hook itself is never manually invoked as proof.

Additional checks use a bounded management-audience IMDS token probe with its
response body discarded and GitHub HTTPS reachability. No third-party IP echo
service is called or accepted as NAT evidence.
A rejected/unreachable IMDS endpoint is limited evidence, NOT proof about every
audience, alternate identity endpoint, or Azure configuration. An external
observer must prove no VM identity attached. Resource-group output is explicitly
an expectation, not cloud-resource attestation. No credentials or environment
dumps are printed. No private PaaS target/access is invented.

NAT evidence belongs to the external ARM observer: read back subnet/NIC
`defaultOutboundAccess=false`, no worker NIC public IP, and the attached NAT,
then correlate with successful worker GitHub connectivity and job completion.
The worker does not query ARM or locally claim those settings are proven.

### Unresolved execution gates

- The spike-specific verifier installation/immutable image pin must be separately
  reviewed in
  [jonathan-vella/azure-gh-runners#81](https://github.com/jonathan-vella/azure-gh-runners/issues/81).
  The shared/container `image/verify-tools.sh` is not the runtime verifier:
  at parent commit `0f9d18acbd46c684c33973a9610b21881bc798f2` it expects the
  shared hook directly and invokes sudo. Do not disguise this mismatch by
  overriding the hook environment.
- Controller custom-label routing, immutable commit/blob policy, root pre-job
  rejection and wrapper-to-shared-policy chaining must be externally observed.
  Worker assertions cannot prove a hook rejected a job before all user steps.
  No speculative negative workflow is included.
- Image/cost approval, reviewed identity/public-consumer policy, recovery and
  cleanup gates, and private PaaS target/auth remain parent decisions.
  [jonathan-vella/azure-gh-runners#10](https://github.com/jonathan-vella/azure-gh-runners/issues/10)
  and ADR-0005 remain open/Proposed; ACA/KEDA evidence is not VMSS evidence.

After review and merge, the owner must approve the resulting immutable main
commit and workflow Git blob SHA for the controller and hook pins. Draft head
pins are review evidence only, never execution-ready approval.

## Offline fixtures

With Python 3.9+ and Bash available, install the pinned YAML test parser via
`python -m pip install -r requirements-dev.txt` (prefer a local virtualenv), then
run `python -m unittest discover -s tests -v`.
Fixtures execute the hosted input validator against allow/reject contexts,
parse the YAML job/input graph, check static policy boundaries, run `bash -n`
on inline shell blocks, assert only IMDS/GitHub network targets, and test
probe exit/status and GitHub connectivity using shell-function curl stubs. They
perform no dispatch, cloud calls, token probes, or runtime assertions. They are
not an Actions expression evaluator or proof of queue matching.
