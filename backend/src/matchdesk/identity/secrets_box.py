"""Re-export: AES-256-GCM sealing moved to the kernel (``tenancy.secrets_box``) in B3 so that ``qbo``
can seal QuickBooks tokens without importing ``identity`` (TRD 5 import rules)."""

from matchdesk.tenancy import SealError, seal, unseal

__all__ = ["SealError", "seal", "unseal"]
