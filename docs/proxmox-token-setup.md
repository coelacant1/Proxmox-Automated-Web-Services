# Proxmox Least-Privilege Token Setup

PAWS connects to your Proxmox VE cluster via an API token. For security, create a dedicated user with minimal permissions instead of using `root@pam`.

## Step 1: Create the PAWS User

On any Proxmox node, run:

```bash
pveum user add paws@pve -comment "PAWS service account"
```

## Step 2: Create the API Token

```bash
pveum acltoken add paws@pve paws -privsep 0
```

Save the displayed token ID and secret - they are shown only once.

**Token ID:** `paws@pve!paws`
**Token Secret:** `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`

> Setting `-privsep 0` means the token inherits all user permissions without further separation. This is simpler to manage.

## Step 3: Assign Minimal Permissions

Create a role with only the permissions PAWS needs:

```bash
pveum role add PAWSRole -privs "VM.Allocate,VM.Audit,VM.Config.Disk,VM.Config.CPU,VM.Config.Memory,VM.Config.Network,VM.Config.Options,VM.Config.Cloudinit,VM.Console,VM.Monitor,VM.PowerMgmt,VM.Snapshot,VM.Backup,VM.Clone,Datastore.Allocate,Datastore.Audit,Datastore.AllocateSpace,SDN.Use,SDN.Audit,Sys.Audit,Sys.Console,Pool.Audit"
```

Assign the role to the PAWS user on the root path:

```bash
pveum acl modify / -user paws@pve -role PAWSRole
```

## Step 4: Configure PAWS

In your `.env` file:

```env
PAWS_PROXMOX_HOST=your-proxmox-host
PAWS_PROXMOX_PORT=8006
PAWS_PROXMOX_TOKEN_ID=paws@pve!paws
PAWS_PROXMOX_TOKEN_SECRET=your-token-secret
PAWS_PROXMOX_VERIFY_SSL=true
```

> **Important:** Set `PAWS_PROXMOX_VERIFY_SSL=true` in production. Only disable SSL verification in development with self-signed certificates.

## Permission Reference

| Permission | Used For |
|-----------|----------|
| VM.Allocate | Create and delete VMs/containers |
| VM.Audit | List and inspect VMs |
| VM.Config.* | Modify VM CPU, RAM, disk, network, cloud-init |
| VM.Console | Open noVNC/xterm.js console |
| VM.Monitor | QEMU monitor access |
| VM.PowerMgmt | Start, stop, reset, shutdown |
| VM.Snapshot | Create and restore snapshots |
| VM.Backup | Run and manage backups |
| VM.Clone | Clone VMs from templates |
| Datastore.Allocate | Create datastores/storage |
| Datastore.Audit | List storage |
| Datastore.AllocateSpace | Upload ISOs, allocate disk space |
| SDN.Use | Assign VMs to SDN networks |
| SDN.Audit | List SDN zones and VNets |
| Sys.Audit | View cluster/node status |
| Sys.Console | Node console access (admin diagnostics) |
| Pool.Audit | View resource pools |

## Verifying Permissions

In the PAWS Admin panel under **Settings**, click **Test Proxmox Connection**. This verifies:

1. API token is valid and not expired
2. Cluster is reachable and has quorum
3. Required permissions are present

If any permissions are missing, the test will report which ones need to be added.

## Security Notes

- **Never use `root@pam`** - if the PAWS token is compromised, an attacker gets full cluster access
- **Rotate tokens periodically** - delete and recreate the API token
- **Enable SSL verification** - prevents man-in-the-middle attacks between PAWS and Proxmox
- **Audit logs** - Proxmox logs all API token usage; review periodically
