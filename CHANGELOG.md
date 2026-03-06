# Changelog

## 0.2.0

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
