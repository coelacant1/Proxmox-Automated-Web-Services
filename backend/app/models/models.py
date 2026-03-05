import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, TypeDecorator, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import CHAR

from app.core.database import Base


class UserRole(enum.StrEnum):
    ADMIN = "admin"
    OPERATOR = "operator"
    MEMBER = "member"
    VIEWER = "viewer"


class GUID(TypeDecorator):
    """Platform-independent UUID type.

    Uses PostgreSQL's UUID type when available, otherwise stores as CHAR(32).
    """

    impl = CHAR(32)
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_UUID(as_uuid=True))
        return dialect.type_descriptor(CHAR(32))

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        if dialect.name == "postgresql":
            return value
        if isinstance(value, uuid.UUID):
            return value.hex
        return uuid.UUID(value).hex

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        if isinstance(value, uuid.UUID):
            return value
        return uuid.UUID(value)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str | None] = mapped_column(String(255), nullable=True)  # null for OAuth-only users
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False)
    role: Mapped[str] = mapped_column(String(20), default=UserRole.MEMBER)  # admin, operator, member, viewer
    auth_provider: Mapped[str] = mapped_column(String(50), default="local")  # local, authentik
    oauth_sub: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)  # OAuth subject ID
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_login_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    resources: Mapped[list["Resource"]] = relationship(back_populates="owner", cascade="all, delete-orphan")
    quota: Mapped["UserQuota"] = relationship(back_populates="user", uselist=False, cascade="all, delete-orphan")
    project_memberships: Mapped[list["ProjectMember"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class UserQuota(Base):
    __tablename__ = "user_quotas"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("users.id"), unique=True)
    max_vms: Mapped[int] = mapped_column(Integer, default=5)
    max_containers: Mapped[int] = mapped_column(Integer, default=10)
    max_vcpus: Mapped[int] = mapped_column(Integer, default=16)
    max_ram_mb: Mapped[int] = mapped_column(Integer, default=32768)  # 32 GB
    max_disk_gb: Mapped[int] = mapped_column(Integer, default=500)
    max_snapshots: Mapped[int] = mapped_column(Integer, default=10)
    max_buckets: Mapped[int] = mapped_column(Integer, default=5)
    max_storage_gb: Mapped[int] = mapped_column(Integer, default=50)  # total S3 storage

    user: Mapped["User"] = relationship(back_populates="quota")


class ProjectRole(enum.StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


class Project(Base):
    """Team/project for grouping resources and sharing access."""

    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("users.id"), index=True)
    is_personal: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    owner: Mapped["User"] = relationship(foreign_keys=[owner_id])
    members: Mapped[list["ProjectMember"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    resources: Mapped[list["Resource"]] = relationship(back_populates="project")


class ProjectMember(Base):
    """Maps users to projects with a project-scoped role."""

    __tablename__ = "project_members"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("projects.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(20), default=ProjectRole.MEMBER)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("project_id", "user_id", name="uq_project_user"),)

    project: Mapped["Project"] = relationship(back_populates="members")
    user: Mapped["User"] = relationship(back_populates="project_memberships")


class Resource(Base):
    """Base resource tracking table - every VM, container, network, etc. is a resource owned by a user."""

    __tablename__ = "resources"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("users.id"), index=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("projects.id"), nullable=True, index=True)
    resource_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)  # vm, lxc, network, storage
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    proxmox_vmid: Mapped[int | None] = mapped_column(Integer, unique=True, nullable=True)  # for VMs/containers
    proxmox_node: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="pending")  # pending, creating, running, stopped, error
    specs: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON blob for flexible metadata
    tags: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON array of tag strings
    termination_protected: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    owner: Mapped["User"] = relationship(back_populates="resources")
    project: Mapped["Project | None"] = relationship(back_populates="resources")


class VMIDPool(Base):
    """Tracks allocated VMIDs to prevent collisions."""

    __tablename__ = "vmid_pool"

    vmid: Mapped[int] = mapped_column(Integer, primary_key=True)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("resources.id"), nullable=True)
    reserved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("users.id"), index=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TemplateCatalog(Base):
    """Admin-curated catalog of Proxmox templates available to users."""

    __tablename__ = "template_catalog"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    proxmox_vmid: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    os_type: Mapped[str | None] = mapped_column(String(50), nullable=True)  # linux, windows, bsd
    category: Mapped[str] = mapped_column(String(20), nullable=False, index=True)  # vm, lxc
    min_cpu: Mapped[int] = mapped_column(Integer, default=1)
    min_ram_mb: Mapped[int] = mapped_column(Integer, default=512)
    min_disk_gb: Mapped[int] = mapped_column(Integer, default=10)
    icon_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    tags: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON array of strings
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class QuotaRequest(Base):
    """User-submitted requests for quota increases (AWS-style)."""

    __tablename__ = "quota_requests"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("users.id"), index=True)
    request_type: Mapped[str] = mapped_column(String(50), nullable=False)  # max_vms, max_vcpus, etc.
    current_value: Mapped[int] = mapped_column(Integer, nullable=False)
    requested_value: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)  # pending, approved, denied
    admin_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship(foreign_keys=[user_id])
    reviewer: Mapped["User | None"] = relationship(foreign_keys=[reviewed_by])


class SystemSetting(Base):
    """Key-value system configuration managed by admins."""

    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)  # JSON-encoded value
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class UserMFA(Base):
    """Multi-factor authentication configuration for a user."""

    __tablename__ = "user_mfa"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("users.id"), unique=True)
    totp_secret: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    backup_codes: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list of hashed codes
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship()


class InstanceType(Base):
    """Pre-defined instance sizes (like EC2 t2.micro, m5.large, etc)."""

    __tablename__ = "instance_types"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)  # e.g. "paws.small"
    vcpus: Mapped[int] = mapped_column(Integer, nullable=False)
    ram_mib: Mapped[int] = mapped_column(Integer, nullable=False)
    disk_gib: Mapped[int] = mapped_column(Integer, nullable=False)
    category: Mapped[str] = mapped_column(String(30), nullable=False, index=True)  # general, compute, memory, storage
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SSHKeyPair(Base):
    """User SSH public keys for injection into VMs/containers."""

    __tablename__ = "ssh_key_pairs"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("users.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    public_key: Mapped[str] = mapped_column(Text, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("owner_id", "name", name="uq_ssh_key_owner_name"),)

    owner: Mapped["User"] = relationship()


class SecurityGroup(Base):
    """Named set of firewall rules (like AWS Security Groups)."""

    __tablename__ = "security_groups"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("users.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("projects.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (UniqueConstraint("owner_id", "name", name="uq_sg_owner_name"),)

    rules: Mapped[list["SecurityGroupRule"]] = relationship(
        back_populates="security_group", cascade="all, delete-orphan"
    )
    owner: Mapped["User"] = relationship()


class SecurityGroupRule(Base):
    """Individual rule within a security group."""

    __tablename__ = "security_group_rules"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    security_group_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("security_groups.id", ondelete="CASCADE"), nullable=False, index=True
    )
    direction: Mapped[str] = mapped_column(String(10), nullable=False)  # ingress, egress
    protocol: Mapped[str] = mapped_column(String(10), nullable=False)  # tcp, udp, icmp
    port_from: Mapped[int | None] = mapped_column(Integer, nullable=True)
    port_to: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cidr: Mapped[str] = mapped_column(String(50), default="0.0.0.0/0")
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)

    security_group: Mapped["SecurityGroup"] = relationship(back_populates="rules")


class ResourceSecurityGroup(Base):
    """Junction table linking resources to security groups."""

    __tablename__ = "resource_security_groups"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    resource_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("resources.id"), nullable=False, index=True)
    security_group_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("security_groups.id"), nullable=False, index=True
    )

    __table_args__ = (UniqueConstraint("resource_id", "security_group_id", name="uq_resource_sg"),)


class Volume(Base):
    """Managed disk volume that can be attached to VMs/containers."""

    __tablename__ = "volumes"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("users.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    size_gib: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_pool: Mapped[str] = mapped_column(String(100), default="local-lvm")
    status: Mapped[str] = mapped_column(String(20), default="available")  # available, attached, deleting
    resource_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("resources.id"), nullable=True)
    disk_slot: Mapped[str | None] = mapped_column(String(20), nullable=True)  # e.g. scsi1, virtio1
    project_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("projects.id"), nullable=True)
    proxmox_node: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    owner: Mapped["User"] = relationship()
    resource: Mapped["Resource | None"] = relationship()


class VPC(Base):
    """Virtual Private Cloud - isolated network for user resources."""

    __tablename__ = "vpcs"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("users.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    cidr: Mapped[str] = mapped_column(String(20), nullable=False)  # e.g. "10.100.0.0/16"
    vxlan_tag: Mapped[int | None] = mapped_column(Integer, nullable=True, unique=True)
    proxmox_zone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    proxmox_vnet: Mapped[str | None] = mapped_column(String(50), nullable=True)
    gateway: Mapped[str | None] = mapped_column(String(20), nullable=True)
    dhcp_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(20), default="active")  # active, deleting
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    project_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("projects.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (UniqueConstraint("owner_id", "name", name="uq_vpc_owner_name"),)

    owner: Mapped["User"] = relationship()
    subnets: Mapped[list["Subnet"]] = relationship(back_populates="vpc", cascade="all, delete-orphan")


class Subnet(Base):
    """Subnet within a VPC."""

    __tablename__ = "subnets"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    vpc_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("vpcs.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    cidr: Mapped[str] = mapped_column(String(20), nullable=False)  # e.g. "10.100.1.0/24"
    gateway: Mapped[str | None] = mapped_column(String(20), nullable=True)
    is_public: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    vpc: Mapped["VPC"] = relationship(back_populates="subnets")


class StorageBucket(Base):
    """S3-compatible storage bucket owned by a user."""

    __tablename__ = "storage_buckets"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(63), unique=True, nullable=False, index=True)
    region: Mapped[str] = mapped_column(String(30), default="local")
    versioning_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    object_count: Mapped[int] = mapped_column(Integer, default=0)
    is_public: Mapped[bool] = mapped_column(Boolean, default=False)
    tags: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    owner: Mapped["User"] = relationship()


class Backup(Base):
    """Record of a backup job (snapshot or PBS-based)."""

    __tablename__ = "backups"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    resource_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("resources.id"), nullable=False)
    owner_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("users.id"), nullable=False)
    backup_type: Mapped[str] = mapped_column(String(20), nullable=False)  # snapshot, full, incremental
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending, running, completed, failed
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    proxmox_storage: Mapped[str | None] = mapped_column(String(100), nullable=True)
    proxmox_volid: Mapped[str | None] = mapped_column(String(200), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    resource: Mapped["Resource"] = relationship()
    owner: Mapped["User"] = relationship()


class BackupPlan(Base):
    """Automated backup schedule for a resource."""

    __tablename__ = "backup_plans"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    resource_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("resources.id"), nullable=False)
    owner_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    schedule_cron: Mapped[str] = mapped_column(String(50), nullable=False)  # cron expression
    backup_type: Mapped[str] = mapped_column(String(20), default="snapshot")
    retention_count: Mapped[int] = mapped_column(Integer, default=7)
    retention_days: Mapped[int] = mapped_column(Integer, default=30)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    config: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON config (notifications, etc.)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    resource: Mapped["Resource"] = relationship()
    owner: Mapped["User"] = relationship()


class ServiceEndpoint(Base):
    """Exposes a resource port to external access via reverse proxy."""

    __tablename__ = "service_endpoints"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    resource_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("resources.id"), nullable=False)
    owner_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    protocol: Mapped[str] = mapped_column(String(10), default="http")  # http, https, tcp
    internal_port: Mapped[int] = mapped_column(Integer, nullable=False)
    subdomain: Mapped[str] = mapped_column(String(63), unique=True, nullable=False, index=True)
    domain_suffix: Mapped[str] = mapped_column(String(100), default="paws.local")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    tls_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    auth_required: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    resource: Mapped["Resource"] = relationship()
    owner: Mapped["User"] = relationship()


class DNSRecord(Base):
    """Internal DNS record for VPC service discovery."""

    __tablename__ = "dns_records"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("users.id"), nullable=False)
    vpc_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("vpcs.id"), nullable=True)
    record_type: Mapped[str] = mapped_column(String(10), nullable=False)  # A, AAAA, CNAME, SRV
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    value: Mapped[str] = mapped_column(String(255), nullable=False)
    ttl: Mapped[int] = mapped_column(Integer, default=300)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    owner: Mapped["User"] = relationship()


class Alarm(Base):
    """Monitoring alarm that fires when a metric crosses a threshold."""

    __tablename__ = "alarms"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("users.id"), nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("resources.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    metric: Mapped[str] = mapped_column(String(50), nullable=False)  # cpu, memory, disk, netin, netout
    comparison: Mapped[str] = mapped_column(String(10), nullable=False)  # gt, gte, lt, lte, eq
    threshold: Mapped[float] = mapped_column(nullable=False)
    period_seconds: Mapped[int] = mapped_column(Integer, default=300)  # evaluation period
    evaluation_periods: Mapped[int] = mapped_column(Integer, default=1)  # consecutive periods
    state: Mapped[str] = mapped_column(String(20), default="ok")  # ok, alarm, insufficient_data
    notify_email: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_webhook: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_state_change_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    resource: Mapped["Resource"] = relationship()
    owner: Mapped["User"] = relationship()


class CostRate(Base):
    """Cost rates for resource billing. Tracks per-resource-type pricing."""

    __tablename__ = "cost_rates"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    resource_type: Mapped[str] = mapped_column(String(20), nullable=False)
    metric: Mapped[str] = mapped_column(String(30), nullable=False)
    rate: Mapped[float] = mapped_column(nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("resource_type", "metric", name="uq_cost_rate"),)


class HealthCheck(Base):
    """Periodic health check results for resources."""

    __tablename__ = "health_checks"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    resource_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("resources.id"), nullable=False, index=True)
    check_type: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    latency_ms: Mapped[float | None] = mapped_column(nullable=True)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LifecyclePolicy(Base):
    """Automated lifecycle policies for instances (auto-stop, auto-start, TTL)."""

    __tablename__ = "lifecycle_policies"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("users.id"), nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("resources.id"), nullable=False, index=True)
    policy_type: Mapped[str] = mapped_column(String(30), nullable=False)  # auto_stop, auto_start, ttl, schedule
    cron_expression: Mapped[str | None] = mapped_column(String(100), nullable=True)
    action: Mapped[str] = mapped_column(String(20), nullable=False)  # stop, start, terminate, hibernate
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    owner: Mapped["User"] = relationship()
    resource: Mapped["Resource"] = relationship()


class Event(Base):
    """System event log - tracks all significant platform events."""

    __tablename__ = "events"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False)  # compute, storage, network, auth, admin
    resource_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("users.id"), nullable=True)
    severity: Mapped[str] = mapped_column(String(10), default="info")  # info, warning, error, critical
    message: Mapped[str] = mapped_column(Text, nullable=False)
    event_metadata: Mapped[str | None] = mapped_column("event_metadata", Text, nullable=True)  # JSON extra data
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CustomMetric(Base):
    """User-pushed custom metrics for monitoring."""

    __tablename__ = "custom_metrics"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("users.id"), nullable=False, index=True)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("resources.id"), nullable=True)
    namespace: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    metric_name: Mapped[str] = mapped_column(String(100), nullable=False)
    value: Mapped[float] = mapped_column(nullable=False)
    unit: Mapped[str | None] = mapped_column(String(30), nullable=True)
    dimensions: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON key-value pairs
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Tag(Base):
    """User-defined tags for organizing resources."""

    __tablename__ = "tags"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("users.id"), nullable=False, index=True)
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    value: Mapped[str] = mapped_column(String(256), default="")
    resource_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("resources.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("resource_id", "key", name="uq_tag_resource_key"),)
