import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr


class UserBase(BaseModel):
    email: EmailStr
    username: str
    full_name: str | None = None


class UserCreate(UserBase):
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str
    mfa_code: str | None = None


class UserRead(BaseModel):
    id: uuid.UUID
    email: str
    username: str
    full_name: str | None = None
    role: str
    is_active: bool
    auth_provider: str
    created_at: datetime

    model_config = {"from_attributes": True}


class QuotaRead(BaseModel):
    max_vms: int
    max_containers: int
    max_vcpus: int
    max_ram_mb: int
    max_disk_gb: int
    max_snapshots: int

    model_config = {"from_attributes": True}


class ResourceBase(BaseModel):
    display_name: str
    resource_type: str


class ResourceRead(ResourceBase):
    id: uuid.UUID
    status: str
    proxmox_node: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


# --- Template Catalog ---


class TemplateCatalogCreate(BaseModel):
    proxmox_vmid: int
    name: str
    description: str | None = None
    os_type: str | None = None
    category: str  # vm or lxc
    min_cpu: int = 1
    min_ram_mb: int = 512
    min_disk_gb: int = 10
    icon_url: str | None = None
    tags: list[str] | None = None


class TemplateCatalogUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    os_type: str | None = None
    min_cpu: int | None = None
    min_ram_mb: int | None = None
    min_disk_gb: int | None = None
    icon_url: str | None = None
    is_active: bool | None = None
    tags: list[str] | None = None


class TemplateCatalogRead(BaseModel):
    id: uuid.UUID
    proxmox_vmid: int
    name: str
    description: str | None
    os_type: str | None
    category: str
    min_cpu: int
    min_ram_mb: int
    min_disk_gb: int
    icon_url: str | None
    is_active: bool
    tags: list[str] | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


# --- Quota Requests ---


class QuotaRequestCreate(BaseModel):
    request_type: str  # max_vms, max_containers, max_vcpus, max_ram_mb, max_disk_gb, max_snapshots
    requested_value: int
    reason: str


class QuotaRequestReview(BaseModel):
    status: str  # approved or denied
    admin_notes: str | None = None


class QuotaRequestRead(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    request_type: str
    current_value: int
    requested_value: int
    reason: str
    status: str
    admin_notes: str | None
    reviewed_by: uuid.UUID | None
    created_at: datetime
    reviewed_at: datetime | None

    model_config = {"from_attributes": True}


# --- System Settings ---


class SystemSettingRead(BaseModel):
    key: str
    value: str
    description: str | None
    updated_at: datetime

    model_config = {"from_attributes": True}


class SystemSettingUpdate(BaseModel):
    value: str


# --- Cluster Status (sanitized) ---


class ClusterNodeStatus(BaseModel):
    name: str
    status: str  # online/offline
    uptime_seconds: int = 0


class ClusterStatusResponse(BaseModel):
    api_reachable: bool
    cluster_name: str | None = None
    node_count: int = 0
    nodes_online: int = 0
    nodes: list[ClusterNodeStatus] = []
    quorate: bool = False


# --- Usage ---


class UsageResponse(BaseModel):
    vms: int = 0
    containers: int = 0
    networks: int = 0
    storage_buckets: int = 0


# --- Audit Logs ---


class AuditLogRead(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    action: str
    resource_type: str | None = None
    resource_id: uuid.UUID | None = None
    details: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


# --- Projects ---


class ProjectCreate(BaseModel):
    name: str
    description: str | None = None


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class ProjectRead(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    description: str | None
    owner_id: uuid.UUID
    is_personal: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class ProjectMemberAdd(BaseModel):
    user_id: uuid.UUID
    role: str = "member"


class ProjectMemberRead(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    user_id: uuid.UUID
    role: str
    created_at: datetime

    model_config = {"from_attributes": True}


# --- MFA ---


class MFASetupResponse(BaseModel):
    secret: str
    provisioning_uri: str
    qr_code_base64: str
    backup_codes: list[str]


class MFAVerifyRequest(BaseModel):
    code: str


class MFAStatusResponse(BaseModel):
    is_enabled: bool
    has_totp: bool


class MFALoginRequest(BaseModel):
    username: str
    password: str
    mfa_code: str


# --- Instance Types ---


class InstanceTypeCreate(BaseModel):
    name: str
    vcpus: int
    ram_mib: int
    disk_gib: int
    category: str = "general"
    description: str | None = None
    sort_order: int = 0


class InstanceTypeRead(BaseModel):
    id: uuid.UUID
    name: str
    vcpus: int
    ram_mib: int
    disk_gib: int
    category: str
    description: str | None
    sort_order: int
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class InstanceTypeUpdate(BaseModel):
    name: str | None = None
    vcpus: int | None = None
    ram_mib: int | None = None
    disk_gib: int | None = None
    category: str | None = None
    description: str | None = None
    sort_order: int | None = None
    is_active: bool | None = None


# --- SSH Key Pairs ---


class SSHKeyCreate(BaseModel):
    name: str
    public_key: str


class SSHKeyRead(BaseModel):
    id: uuid.UUID
    name: str
    public_key: str
    fingerprint: str
    created_at: datetime

    model_config = {"from_attributes": True}


# --- Security Groups ---


class SecurityGroupRuleCreate(BaseModel):
    direction: str  # ingress, egress
    protocol: str  # tcp, udp, icmp
    port_from: int | None = None
    port_to: int | None = None
    cidr: str = "0.0.0.0/0"
    description: str | None = None


class SecurityGroupRuleRead(BaseModel):
    id: uuid.UUID
    direction: str
    protocol: str
    port_from: int | None
    port_to: int | None
    cidr: str
    description: str | None

    model_config = {"from_attributes": True}


class SecurityGroupCreate(BaseModel):
    name: str
    description: str | None = None


class SecurityGroupRead(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    rules: list[SecurityGroupRuleRead] = []
    created_at: datetime

    model_config = {"from_attributes": True}


# --- Volumes ---


class VolumeCreate(BaseModel):
    name: str
    size_gib: int
    storage_pool: str = "local-lvm"


class VolumeRead(BaseModel):
    id: uuid.UUID
    name: str
    size_gib: int
    storage_pool: str
    status: str
    resource_id: uuid.UUID | None
    disk_slot: str | None
    proxmox_node: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


# --- VPC / Networking ---


class SubnetCreate(BaseModel):
    name: str
    cidr: str
    gateway: str | None = None
    is_public: bool = False


class SubnetRead(BaseModel):
    id: uuid.UUID
    name: str
    cidr: str
    gateway: str | None
    is_public: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class VPCCreate(BaseModel):
    name: str
    cidr: str = "10.100.0.0/16"
    gateway: str | None = None
    dhcp_enabled: bool = True


class VPCRead(BaseModel):
    id: uuid.UUID
    name: str
    cidr: str
    vxlan_tag: int | None
    proxmox_zone: str | None
    proxmox_vnet: str | None
    gateway: str | None
    dhcp_enabled: bool
    status: str
    is_default: bool
    subnets: list[SubnetRead] = []
    created_at: datetime

    model_config = {"from_attributes": True}
