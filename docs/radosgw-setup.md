# Ceph RadosGW (S3 Gateway) Setup for PAWS

PAWS uses Ceph RadosGW as its S3-compatible object storage backend. This guide covers enabling RadosGW on a Proxmox VE cluster where Ceph was set up via `pveceph`.

> **Note:** Proxmox manages Ceph directly (not via cephadm), so `ceph orch` commands will not work. RadosGW must be installed and configured manually.

## Prerequisites

- Proxmox VE cluster with Ceph installed via `pveceph` and healthy (`ceph -s` shows `HEALTH_OK`)
- SSH root access to at least one Proxmox node

Verify your cluster is ready:

```bash
ceph -s
ceph osd pool ls
```

## Step 1: Install RadosGW Package

On **each node** that will run a gateway daemon (recommend 2-3 for HA):

```bash
apt update
apt install -y radosgw
```

## Step 2: Create the RGW Keyring

On one node, create keyrings for the RadosGW daemons:

```bash
ceph auth get-or-create client.rgw.rgw0 \
  osd 'allow rwx' \
  mon 'allow rw' \
  -o /etc/ceph/ceph.client.rgw.rgw0.keyring

ceph auth get-or-create client.rgw.rgw1 \
  osd 'allow rwx' \
  mon 'allow rw' \
  -o /etc/ceph/ceph.client.rgw.rgw1.keyring

ceph auth get-or-create client.rgw.rgw2 \
  osd 'allow rwx' \
  mon 'allow rw' \
  -o /etc/ceph/ceph.client.rgw.rgw2.keyring
```

> **Important (Proxmox):** Proxmox-managed Ceph looks for keyrings in `/etc/pve/priv/`, **not** `/etc/ceph/`. You must copy each keyring to the Proxmox path or the daemon will fail with `unable to find a keyring`:

```bash
cp /etc/ceph/ceph.client.rgw.rgw0.keyring /etc/pve/priv/ceph.client.rgw.rgw0.keyring
```

Repeat on each node for its respective keyring (`rgw1`, `rgw2`, etc.).

## Step 3: Configure RadosGW

Add the following to `/etc/ceph/ceph.conf`. Adjust the `host` and daemon name per node:

```ini
[client.rgw.rgw0]
host = pvetest01
rgw_frontends = "beast port=7480"
rgw_thread_pool_size = 512
rgw_dns_name = s3.your-domain.com

[client.rgw.rgw1]
host = pvetest02
rgw_frontends = "beast port=7480"
rgw_thread_pool_size = 512

[client.rgw.rgw2]
host = pvetest03
rgw_frontends = "beast port=7480"
rgw_thread_pool_size = 512
```

> **Tip:** On Proxmox, `/etc/ceph/ceph.conf` is synced across nodes via `pveceph`. You can add all `[client.rgw.*]` sections on one node and they will propagate, but you still need the package and keyring on each node.

## Step 4: Start the RadosGW Service

On each node running a gateway:

```bash
systemctl enable --now ceph-radosgw@rgw.rgw0

# Verify status
systemctl status ceph-radosgw@rgw.rgw0
```

> **Note:** RadosGW can take 10-20 seconds after startup before it binds to the port. The LDAP warning (`LDAP not started since no server URIs were provided`) is informational and can be ignored.

Verify it responds:

```bash
# Check the port is listening
ss -tlnp | grep 7480

# Test the endpoint (empty Host header avoids virtual-host bucket lookup)
curl http://localhost:7480/ -H "Host: "
```

You should see an XML `ListAllMyBucketsResult` response - this confirms RadosGW is running.

## Step 5: Create the PAWS Admin User

Create a RadosGW user with full admin capabilities for PAWS to manage buckets and objects:

```bash
radosgw-admin user create \
  --uid=paws-admin \
  --display-name="PAWS Admin" \
  --caps="buckets=*;users=*;metadata=*;usage=*;zone=*"
```

The output will include `access_key` and `secret_key` in the `keys` array:

```json
{
    "user_id": "paws-admin",
    "keys": [
        {
            "access_key": "XXXXXXXXXXXXXXXXXXXX",
            "secret_key": "YYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYY"
        }
    ]
}
```

**Save these credentials** - you will need them for the PAWS `.env` configuration.

To retrieve the keys later:

```bash
radosgw-admin user info --uid=paws-admin
```

## Step 6: Verify S3 Access

Test that the credentials work. Using the AWS CLI:

```bash
# Install if needed: pip install awscli
aws --endpoint-url http://localhost:7480 s3 ls

# Create and remove a test bucket
aws --endpoint-url http://localhost:7480 s3 mb s3://test-bucket
aws --endpoint-url http://localhost:7480 s3 rb s3://test-bucket
```

> If you haven't configured `~/.aws/credentials`, pass keys inline:
> ```bash
> AWS_ACCESS_KEY_ID=XXXX AWS_SECRET_ACCESS_KEY=YYYY aws --endpoint-url http://localhost:7480 s3 ls
> ```

## Step 7: Configure PAWS

Update your PAWS `.env` file with the RadosGW endpoint and credentials:

```env
PAWS_S3_ENDPOINT_URL=http://<proxmox-node-ip>:7480
PAWS_S3_ACCESS_KEY=XXXXXXXXXXXXXXXXXXXX
PAWS_S3_SECRET_KEY=YYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYY
PAWS_S3_REGION=us-east-1
PAWS_S3_USE_SSL=false
```

If running behind a reverse proxy with TLS:

```env
PAWS_S3_ENDPOINT_URL=https://s3.your-domain.com
PAWS_S3_USE_SSL=true
```

---

## DNS & Reverse Proxy Setup

RadosGW listens on port 7480 by default. For production, put it behind a reverse proxy with a proper domain name.

### Cloudflare DNS

1. Create an **A record** pointing to your Proxmox node (or load balancer IP):
   - `s3.your-domain.com` -> `<node-ip>`
   - Proxy status: **DNS only** (grey cloud) - Cloudflare's HTTP proxy can interfere with S3 signatures and large uploads
2. If running multiple RGW daemons, either:
   - Point the A record to a load balancer that distributes across all RGW nodes
   - Create multiple A records (round-robin DNS) for each node IP

> **Important:** Do **not** enable Cloudflare's orange-cloud proxy for the S3 endpoint. AWS Sig V4 signing is sensitive to header manipulation, and Cloudflare's 100MB free-tier upload limit will block large object uploads.

### Nginx Reverse Proxy

```nginx
upstream radosgw {
    server pvetest01:7480;
    server pvetest02:7480;
    server pvetest03:7480;
}

server {
    listen 443 ssl;
    server_name s3.your-domain.com;

    ssl_certificate     /etc/ssl/certs/your-cert.pem;
    ssl_certificate_key /etc/ssl/private/your-key.pem;

    client_max_body_size 5G;

    # Disable buffering for streaming uploads
    proxy_buffering off;
    proxy_request_buffering off;

    location / {
        proxy_pass http://radosgw;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
    }
}
```

If using Cloudflare with SSL, you can use a Cloudflare Origin Certificate for the `ssl_certificate` and set SSL mode to **Full (strict)** in the Cloudflare dashboard.

### Single-Node Shortcut (no Nginx)

If you only run one RGW daemon, you can have RadosGW serve TLS directly:

```ini
[client.rgw.rgw0]
host = pvetest01
rgw_frontends = "beast port=443 ssl_port=443 ssl_certificate=/etc/ssl/certs/your-cert.pem ssl_private_key=/etc/ssl/private/your-key.pem"
rgw_thread_pool_size = 512
rgw_dns_name = s3.your-domain.com
```

---

## Optional: Default Quotas

Set default quotas for the PAWS admin user (PAWS manages its own quotas at the application level, but this adds a safety net):

```bash
radosgw-admin quota set --quota-scope=user --uid=paws-admin \
  --max-size=50G --max-objects=100000

radosgw-admin quota enable --quota-scope=user --uid=paws-admin
```

---

## Troubleshooting

**`ceph orch` commands fail with "No orchestrator configured":**
This is expected on Proxmox-managed Ceph. Proxmox uses `pveceph`, not cephadm. Follow the manual install steps above.

**RadosGW fails with "unable to find a keyring":**
The keyring exists at `/etc/ceph/` but Proxmox looks in `/etc/pve/priv/`. Copy it:
```bash
cp /etc/ceph/ceph.client.rgw.rgw0.keyring /etc/pve/priv/ceph.client.rgw.rgw0.keyring
systemctl restart ceph-radosgw@rgw.rgw0
```

**RadosGW service won't start:**
```bash
systemctl status ceph-radosgw@rgw.rgw0
journalctl -u ceph-radosgw@rgw.rgw0 --no-pager -n 50

# Verify keyring exists in both locations
ls -la /etc/ceph/ceph.client.rgw.rgw0.keyring
ls -la /etc/pve/priv/ceph.client.rgw.rgw0.keyring
ceph auth get client.rgw.rgw0
```

**Port 7480 not responding after service starts:**
RadosGW takes 10-20 seconds to bind after startup. Wait, then check:
```bash
ss -tlnp | grep 7480
grep -A5 'client.rgw' /etc/ceph/ceph.conf
```

**`curl http://localhost:7480` returns `NoSuchBucket`:**
This is normal - `curl` sends `Host: localhost` which RGW interprets as a virtual-hosted bucket name. Use `curl http://localhost:7480/ -H "Host: "` instead, or use the AWS CLI.

**Access denied with valid credentials:**
```bash
radosgw-admin user info --uid=paws-admin

# Re-add caps if missing
radosgw-admin caps add --uid=paws-admin \
  --caps="buckets=*;users=*;metadata=*;usage=*;zone=*"
```

**Pools not created:**
RadosGW automatically creates its pools (`.rgw.root`, `default.rgw.buckets.data`, etc.) on first use. If they don't appear after the first S3 operation:
```bash
ceph osd pool ls | grep rgw
ceph -s
```
