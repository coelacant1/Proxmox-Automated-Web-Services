# Changelog

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
- StatusBadge component added `provisioning` → `info` variant mapping

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
