# Amination Forge Runner — dormant deployment package

This package prepares an independent Debian/Ubuntu Linux host for the Forge
runner. It does not provision a cloud VM, create a cloud account, or start
anything on the developer's Android phone.

## Architecture

- Amination AI remains the application and orchestration layer.
- This host runs the authenticated Python runner service under systemd.
- Docker runs candidate commands in isolated containers.
- Caddy can provide public HTTPS when a domain is available.
- The runner listens on 127.0.0.1:8765. Do not expose that port publicly.

## Requirements when activating

- A dedicated Debian or Ubuntu Linux VM.
- A domain name with DNS pointed at that VM for public HTTPS.
- SSH access and an administrator account.
- Docker-capable host resources appropriate for the selected toolchains.

## Prepare the host later

1. Provision the Linux VM.
2. Copy or securely clone the Amination AI repository to `/opt/amination-ai`.
   The installer supports project paths under `/opt` only; do not place the service project under `/home` or `/root`.
3. Copy this deployment directory with the repository.
4. Run as root:

   `bash /opt/amination-ai/deploy/forge-runner/install-host.sh`

The script installs the host packages, creates the dedicated runner account,
builds the execution image, creates a random bearer token if no configuration
already exists, and installs the systemd unit.

It deliberately leaves the service **disabled and stopped**.

## Activate

After reviewing the generated configuration:

`sudo bash /opt/amination-ai/deploy/forge-runner/activate.sh`

The activation script starts the service and checks its readiness endpoint.

## Deactivate without deleting data

`sudo bash /opt/amination-ai/deploy/forge-runner/deactivate.sh`

This stops and disables the service. It does not delete the runner data,
configuration, or Docker image.

## Configuration

The generated configuration is:

`/etc/amination-forge/runner.env`

It contains the bearer token. Keep it private and never commit it.

The shared configuration validator enforces these safety requirements:
- Runner data must remain at `/var/lib/amination-forge`.
- The service must bind only to `127.0.0.1`.
- The port must be between 1 and 65535.
- The Docker image name must be non-empty and contain no whitespace.

The installer, activation script and status script all use the same validator.

The runner defaults to localhost binding. Put Caddy or another trusted HTTPS
reverse proxy in front of it. The example Caddy configuration is in
`Caddyfile.example`.

On the Amination AI application host, configure these secrets separately:

- `FORGE_RUNNER_URL=https://your-runner-domain`
- `FORGE_RUNNER_TOKEN=<same secret as the runner host>`

Do not put the token in browser JavaScript, source control, or user-visible logs.

## Security notes

The runner account needs access to the Docker socket. Membership in the Docker
group is effectively root-equivalent on the host. Therefore:

- Use a dedicated VM, not a shared sensitive application host.
- Restrict SSH access and enable security updates.
- Expose only SSH, HTTP and HTTPS at the firewall.
- Keep runner port 8765 private.
- Use a strong unique token and rotate it if exposed.
- Do not expose the runner directly to untrusted clients.
- Keep the Docker image and host packages updated.

Docker containers are isolated execution environments, not a substitute for
host security. The existing runner's no-network, resource, filesystem and
process restrictions remain important.

Resource settings are operational safeguards for the VM, not limits on
Forge's reasoning or project scope. Tune them to the actual host capacity.

## Health endpoint

`GET /healthz` is intentionally unauthenticated for reverse-proxy monitoring.
It returns only generic readiness information. It checks both Docker daemon
availability and whether the configured runner image exists.

All session and execution endpoints continue to require bearer authentication.

## Current status

This package is deployment preparation only. No VM has been provisioned, no
public endpoint exists, and no live runner is claimed to be operating.
