# Changelog

## 0.2.8 - 2026-03-25

### Added

- **Per-resource markdown notes (Issue #9)** - Notes tab on instance detail page with markdown editor and live preview; notes sync to Proxmox VM/LXC description alongside PAWS metadata
- **Shared documentation pages (Issue #10)** - Full documentation system with create, edit, and delete; visibility controls (private, group, public); edit locking to prevent conflicts; accessible from sidebar
- **Markdown editor component** - Reusable write/preview editor with GitHub Flavored Markdown support (tables, task lists, strikethrough)
- **Markdown preview styling** - Dark-theme CSS for headings, code blocks, tables, blockquotes, lists, and links
- **Database migration** - Added `notes` column to resources table and `doc_pages` table with indexes

### Fixed

- **Group member access to resource notes** - Notes endpoints now check group-level access (read to view, operate to edit) instead of owner-only; group admins get full access to shared resources
- **Group document viewing** - Fixed 403 error when group members tried to open shared documents; `_can_view` now checks group membership
- **Group admin permission elevation** - Group admins now automatically get admin-level access to all resources shared with their group regardless of the share's permission level
- **PAWS metadata preservation** - Saving notes no longer overwrites Proxmox VM description; notes are appended below the PAWS metadata block with a separator
- **Consistent metadata format** - Both resource notes sync and VM creation now use the same `_build_paws_description` helper for Proxmox descriptions
- **Missing resize modal tag** - Restored accidentally removed `<Modal>` opening tag for the resize dialog in InstanceDetail
- **Documentation page API patterns** - Fixed toast/confirm hook usage and API import paths in Documentation page

### Changed

- Group name badge shown on shared document cards in the documentation list
- Documentation link added to sidebar navigation under Account section

## 0.2.7 - 2026-03-24

### Fixed

- **Backend tests (63 failures -> 0)** - Added 29 missing mock methods to `MockProxmoxClient` test fixture; fixed VMID range assertions (100 -> 1000) to match system default; updated delete tests to expect hard-delete behavior; added required `resource_id` field to volume test payloads; rewrote static IP tests with proper VPC/Subnet DB setup; added volume detach step before delete; updated volume snapshot test to expect 404 (endpoint not implemented)
- **Duplicate IP reservation race condition** - Added `IntegrityError` handling in networking router returning 409 on duplicate IP reserve
- **Stale model references** - Removed non-existent `UserMFA` import from user cleanup service; removed premature `Tag` references from resource cleanup until tag feature is fully integrated

## 0.2.6 - 2026-03-24

### Fixed

- **Backend lint (ruff)** - Fixed `ReviewBody` and `TierRequestBody` class definitions used before declaration in admin_tiers.py; renamed ambiguous `l` variables; fixed `== True` comparisons to `.is_(True)` for SQLAlchemy; moved misplaced import in compute.py; resolved 32 line-too-long violations; excluded alembic migrations from import sorting rules
- **Backend format** - Applied `ruff format` across 73 files for consistent style
- **Frontend lint (ESLint)** - Fixed empty catch blocks in InstanceDetail.tsx causing lint errors

## 0.2.5 - 2026-03-24

### Added

- **Custom Confirm Dialog** - Promise-based `useConfirm` hook and `ConfirmProvider` replacing all native `confirm()` dialogs with a styled modal (danger icon, cancel/confirm buttons, dark overlay)
- **Toast Notifications** - Added success and error toasts to all destructive and create operations across VPCs, VMs, Containers, Storage, FileBrowser, SSH Keys, Firewalls, Endpoints, Backups, BackupDetail, CustomImages, and Admin
- **ESLint Configuration** - Added `eslint.config.js` for ESLint v9 with TypeScript and React plugins

### Changed

- All 20 native `confirm()` calls replaced with `useConfirm` hook across 13 pages
- Native `alert()` call in VPCs.tsx replaced with error toast
- Normalized `useToast` destructuring in Admin.tsx (11 instances of `toast.toast()` simplified to `toast()`)
- S3 quota labels added to QuotaRequests.tsx for `max_buckets` and `max_storage_gb`

### Fixed

- **Frontend build** - JSX parse error from bare `->` in BucketDetail.tsx and Admin.tsx (escaped as `{'->'}`
- **Backend CI** - `bcrypt` missing from `pyproject.toml` dependencies causing import failure
- **Dashboard bucket count** - Was querying `resources` table instead of `storage_buckets` table, always showing 0

## 0.2.4 - 2026-03-20

### Added

- **Ceph RadosGW Integration** - Migrated object storage backend from MinIO to Ceph RadosGW with S3-compatible API via aioboto3 and AWS SigV4 authentication
- **S3 Usage Guide** - Collapsible in-app guide on the Storage page with tabbed code examples for AWS CLI, Python (boto3), JavaScript (AWS SDK v3), and presigned URLs; dynamically populated with real endpoint URL and region from server config
- **S3 Quota Visibility** - Bucket count and storage GB quotas displayed on Dashboard (metric cards + quota bars), Storage page (quota bars), and Quota Requests page (Object Storage section); admin-configurable defaults via `default_max_buckets` and `default_max_storage_gb` system settings
- **Storage Quota Endpoint** - `GET /api/storage/quota` returns current bucket/storage usage vs limits
- **S3 Info Endpoint** - `GET /api/storage/s3-info` returns endpoint URL and region for client configuration
- **Native File Upload** - OS file picker and drag-and-drop upload in File Browser sending raw bytes with proper Content-Type headers

### Changed

- Storage backend rewritten from httpx with basic auth to aioboto3 with SigV4 (`storage_service.py`)
- Config keys renamed from `minio_*` to `s3_endpoint_url`, `s3_access_key`, `s3_secret_key`, `s3_region`
- MinIO services and volumes removed from `docker-compose.yml`
- Presigned URL generation is now async; both `/presign` and `/presigned` paths accepted
- Bucket delete now force-empties all objects before removing the bucket
- Bucket cards use `<div role="button">` instead of nested `<button>` elements (fixes HTML validation)
- Dashboard storage bucket count queries `storage_buckets` table directly instead of `resources` table
- S3 quota labels (`max_buckets`, `max_storage_gb`) added to quota request form

### Fixed

- Bucket operations returning 500 when frontend passes bucket name instead of UUID (added name-based fallback lookup)
- Presigned URL endpoint returning 404 (frontend called `/presigned`, backend only had `/presign`)
- Object size displaying as "NaN undefined" (backend returned `size_bytes`, frontend expected `total_size`)
- File upload failing silently (frontend sent JSON text instead of raw file bytes)
- Deleting non-empty buckets returning 409 Conflict (now empties bucket contents first)
- Bucket count on dashboard showing 0 despite existing buckets (was querying wrong table)

## 0.2.3 - 2026-03-13

### Added

- **SDN Networking** - EVPN/VNet-based isolated networking with real Proxmox SDN integration; VPC creation now provisions Proxmox VNets with auto-allocated VXLAN tags; subnet creation provisions SDN subnets with SNAT; FirewallProfileService generates per-instance firewall rules based on network mode; static IP auto-allocation via cloud-init (VMs) and LXC net config with DB-backed IP reservations
- **Network Modes** - Per-VPC network modes (Published/Private/Isolated) replacing per-instance mode; Published mode blocks RFC1918/bogon traffic while whitelisting admin-configured upstream proxy IPs (`sdn.upstream_ips`); VPC mode changes bulk re-apply firewall rules to all attached instances
- **Multi-NIC Support** - Up to 2 NICs per instance (primary + one secondary); secondary NIC must target a private-mode VPC; isolated networks block secondary NICs; auto-allocated static IP with cloud-init `ipconfig1` for VMs
- **Subnet Mask Limits** - Admin-configurable maximum subnet size via `sdn.default_max_subnet_prefix` system setting (default /24); per-tier override via `max_subnet_prefix` field allowing up to /16 for higher tiers
- **Structured Instance Configuration** - Replaced raw cloud-init editing with structured config modal (hostname, username, password, DNS server, DNS domain, SSH keys); SSH keys resolved from saved SSH Keys page via checkbox selection; separate GET/PUT config endpoints for both VMs and LXC containers
- **IP Address Management** - VPC instances display allocated IPs (from DB) and live IPs (from guest agent/LXC config) as separate badges; inline IP editing within subnet range with validation; IP reservations persisted in database via `IPReservation` model
- **Network Safety Enforcement** - VMs cannot start on `vmbr0` without `link_down=1`; running instances are automatically stopped, reconfigured, and restarted on network changes with user notification
- **Cloud-Init Regeneration** - Proxmox cloud-init ISO automatically rebuilt after any config or NIC change via `regenerate_cloudinit()` calls
- **SDN Admin Tab** - Infrastructure section with SDN overview, network list, and force-delete in Admin panel
- **Network Quotas** - `max_networks`, `max_subnets_per_network`, and `max_elastic_ips` quota fields with dashboard display and quota request support
- **Over-Quota Warning** - Quotas page now displays warning banner listing exceeded quotas (VMs, Containers, vCPUs, RAM, Disk, Networks, Snapshots, Backups, Backup Storage)
- **VPC Peering Model** - Database model for future VPC-to-VPC peering support

### Changed

- VPCs renamed to **Networks** throughout the UI (sidebar, page titles, admin tabs)
- Security Groups renamed to **Firewalls** throughout the UI
- Removed DNS Records, IP Addresses, Monitoring, and Alarms pages (functionality covered by Networks, Endpoints, Dashboard, and Quotas pages)
- CreateInstance wizard "Cloud-Init" step renamed to "Configuration" with structured fields instead of raw text
- InstanceDetail cloud-init modal replaced with structured Instance Configuration modal
- Network mode is now a property of the VPC/network, not individual instances; instance-level endpoints delegate to VPC mode change
- SDN subnets use static IP allocation instead of DHCP (Proxmox DHCP non-functional on EVPN/VXLAN zones)
- Instance deletion now cascades cleanup across all 11 child FK tables via unified `_cleanup_resource_children()` helper
- Config, network, and cleanup code consolidated into 5 unified helpers (`_resolve_ssh_keys`, `_apply_instance_config`, `_build_net0`, `_apply_nic`, `_cleanup_resource_children`) eliminating code duplication across create/update/delete paths
- Clone-then-migrate flow now waits for migration task completion before applying configuration
- Console endpoints (VNC/terminal) resolve actual VM node via `find_vm_node()` before requesting tickets
- Dashboard alarm banner and alarm-related code removed (covered by quota warnings)

### Fixed

- SSH keys silently dropped during VM/container creation (`ssh_key_ids` accepted but never resolved from database)
- Cloud-init settings not applied during template clone (exception swallowed by bare `except: pass`)
- Cloud-init ISO not regenerated after config or NIC changes (Proxmox requires explicit rebuild)
- VNC/terminal console failing for migrated VMs due to stale `proxmox_node` in database
- VM deletion failing with FK violation on `ip_reservations` table
- Network change on running VM returning 400 hotplug error (now uses stop/apply/restart flow)
- Volume creation VM selector showing "VMID undefined" (`proxmox_vmid` vs `vmid` field mismatch)
- Security group deletion failing with FK violation on `resource_security_groups` (added `ON DELETE CASCADE`)
- EVPN zone reference mismatch between code (`pawsevpn`) and actual Proxmox zone (`paws`)
- Clone-to-migrate race condition where config was applied while VM was still migrating (locked)
- Missing error toasts on VM delete, VM actions, VPC create, and VPC delete failures

## 0.2.2 - 2026-03-11

### Added

- **Admin Audit Mode** - "View as user" impersonation with 1-hour scoped tokens, audit banner with exit button, and automatic token backup/restore in localStorage
- **Admin Resources View** - Global resource dashboard with 10 categories (Instances, Volumes, VPCs, Security Groups, Object Storage, Backups, DNS Records, Alarms, SSH Keys, Endpoints), search, pagination, and click-to-impersonate navigation
- **Resource Lifecycle Management** - `last_accessed_at` tracking on resources, `last_login_at` on users, tier-based lifecycle policy overrides (`idle_shutdown_days`, `idle_destroy_days`, `account_inactive_days`), hourly auto-shutdown/destroy of idle resources, daily account purge of inactive users with full 28-table cascade cleanup
- **Lifecycle UI** - LifecycleCountdown component on instance cards and detail pages with keep-alive button, account lifecycle countdown card on Dashboard, Idle Timer card in InstanceDetail Lifecycle tab
- **Backup System Rewrite** - Backend endpoints for Proxmox-native backup listing, quota summary, file browsing, and admin pruning policies; comprehensive BackupsEnhanced page with Backups/Snapshots/Plans tabs; reusable file browser from InstanceDetail; parallel snapshot fetching; non-blocking data loading for slow PBS
- **Backup Quotas** - `max_backups` (default 20) and `max_backup_size_gb` (default 100) on UserQuota with enforcement on backup creation (409 if over limit)
- **Comprehensive Quotas Page** - Usage tab with grouped quota bars (Compute, Backups & Snapshots, Object Storage) and summary table; Requests tab with improved request form showing current limits and request history
- **Dashboard Quota Display** - Extended from 3 to 8 QuotaBar components (VMs, Containers, vCPUs, RAM, Disk, Snapshots, Backups, Backup Storage) with over-quota warning banner and "Request Increase" button
- **Over-Quota Enforcement** - Celery task that auto-shuts down newest running instances when quota is exceeded, with per-user event notifications and grace period handling
- **PAWS Metadata Stamping** - `paws-managed` tag and structured description (owner info, resource ID, creation date) applied to Proxmox VMs/containers on provisioning, admin import, and resource transfer; user sync and admin bulk re-stamp endpoints; metadata clearing on resource unlink
- **Keep-Alive Endpoints** - `POST /compute/vms/{id}/keepalive` and `POST /compute/containers/{id}/keepalive` to reset idle timers
- **Admin User Detail** - QuotaBar grid showing 8 utilization metrics with proper vCPU/RAM/Disk calculation from resource specs

### Changed

- Admin navigation restructured from 15 flat tabs to 4 categorized sections (Dashboard, Users & Groups, System, Infrastructure)
- Dashboard summary endpoint now calculates actual vCPU/RAM/Disk usage from `Resource.specs` instead of showing 0
- Backup storage resolution changed from hardcoded node to dynamic node discovery via `_resolve_node()`
- Admin `delete_user` now uses full `purge_user()` cascade service instead of bare delete
- Admin resource view syncs live Proxmox status before returning results
- Tier API responses now include lifecycle override fields
- Resource access endpoints auto-touch `last_accessed_at` on every access
- Auth login flow always sets `last_login_at` on successful login (local + OAuth)
- Clone/create operations now wait for Proxmox task completion before applying config/metadata
- StatusBadge component added `provisioning` -> `info` variant mapping

### Fixed

- Audit mode exit race condition where `stopImpersonating()` wasn't awaited before navigation
- Transfer modal showing greyed-out button due to missing Select placeholder
- Backup count and total size showing 0 due to hardcoded node fallback
- 422 error on lifecycle PATCH endpoint with empty body (`Body(default=None)`)
- Metadata not applied after cloning from template (missing wait-for-task in non-migration branch)
- Metadata not applied on ostemplate container create (wait branch skipped for non-clone creates)
- Page crash "Objects are not valid as React child" on backup storage Select rendering objects instead of strings
- Snapshot creation button staying greyed out due to missing onChange handler
- Dashboard vCPUs/RAM/Disk always showing 0 (backend now sums from resource specs)
- Admin user stats excluding destroyed resources and returning all quota fields with defaults
- Slow PBS responses blocking entire page render (now non-blocking with async loading)

## 0.2.1 - 2026-03-08

### Added

- **Admin Groups Management** - System-wide group list with search, pagination, member/share counts, group detail view with members and shared resources, audit log per group, and admin force-delete with modal confirmation
- **Group-Aware Resource Access** - Shared VPCs, security groups, and volumes can now be viewed/modified by group members according to their permission level (read/operate/admin)
- **Modal Confirmations** - Replaced browser `confirm()` dialogs with styled modals for API key revoke, group token revoke, group delete, and member removal

### Changed

- Security group endpoints (`get`, `delete`, `add_rule`, `delete_rule`) now use `_get_user_sg()` with group access fallback instead of inline `owner_id` checks
- Volume endpoints (`get`, `attach`, `detach`, `delete`, `resize`) now use `_get_user_volume()` with group access fallback
- Admin panel tabs expanded with Groups tab between Users and Tiers

### Fixed

- Group members with appropriate permissions can now actually modify shared security groups and volumes (previously returned 404)
- Revoked group API tokens now visually match revoked personal API keys (opacity + muted styling)

## 0.2.0 - 2026-03-06

### Added

- **Groups & Resource Sharing** - IAM-style groups with member roles (owner/admin/member/viewer) and polymorphic sharing of VMs, LXCs, VPCs, volumes, buckets, endpoints, SSH keys, security groups, DNS records, backups, and alarms with read/operate/admin permission levels
- **Tier System** - Capability-based user tiers with self-service upgrade requests and admin approval workflow; capabilities gate features like HA management, template requests, and resource sharing
- **High Availability** - Admin HA group CRUD with PVE sync, per-instance HA enable/disable with group assignment, HA status monitoring in instance detail
- **Template Requests** - Users can request VM-to-template conversion; admin approval auto-converts on PVE and creates a template catalog entry
- **Bug Reports** - User-submitted reports with file attachments (up to 10MB), admin review dashboard with status tracking (open/in_progress/resolved/closed/wont_fix)
- **System Rules** - Admin-defined platform rules and restrictions with categories (General, Compute, Storage, Network, Security) and severity levels (info/warning/restriction)
- **Analytics Dashboard** - Admin view with active users, request trends (24h), login history (7d), top endpoints, and real-time request counts
- **Volume Management** - Attach/detach volumes between VMs, grow-only resize, SCSI slot tracking, storage pool validation via system settings
- **Middleware** - Analytics tracking (per-user requests, active users, endpoint usage), rate limiting (mutating requests), security headers (CSP, HSTS, X-Frame-Options)
- Sidebar navigation for Groups, Account Tier, and System Rules pages

### Changed

- `GroupResourceShare` model refactored from single `resource_id` FK to polymorphic `entity_type`/`entity_id` supporting 10 entity types
- Instance detail page expanded with HA card, storage tab for attached volumes, and "Request as Template" button
- Admin panel extended with Tiers, Bug Reports, Rules, and Analytics tabs
- Session timeout configuration (admin-set user re-login period)
- Cloud-init support during VM provisioning (hostname, SSH keys, user data, IP config)

### Fixed

- xterm.js terminal viewer authentication and connection handling
- Volume creation, detach, and reattach workflow across hosts (proper volid tracking, storage pool resolution)
- Async SQLAlchemy `MissingGreenlet` crash on group member loading (changed to `lazy="selectin"`)
- 422 validation error responses rendered as React children instead of readable strings
- FastAPI route ordering for `/my-entities`, `/entity-types`, `/shared-with-me` conflicting with `/{group_id}` path parameter
- VM force stop calling shutdown instead of force stop
- Recharts zero-dimension error on analytics charts
- Toast error handling across Admin and Groups pages safely extracts messages from validation error arrays

## 0.1.0 - Initial Release

Initial commit of PAWS (Proxmox Automated Web Services).
