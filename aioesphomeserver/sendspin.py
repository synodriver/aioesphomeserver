"""Backend hook for Sendspin pairing token requests over encrypted Native API."""

from __future__ import annotations

from aioesphomeapi.model import (
    SendspinFeature,
    SendspinPairingTokenResponse,
    SendspinPairingTokenStatus,
)


class SendspinProvider:
    """Attach an existing Sendspin backend; this class does not stream audio."""

    def __init__(
        self, *, client_id: str = "",
        feature_flags: int = SendspinFeature.PAIRING_TOKEN,
    ) -> None:
        self.client_id = client_id
        self.feature_flags = int(feature_flags)

    async def on_pairing_token(self) -> SendspinPairingTokenResponse:
        """Return backend status and token. Never log the long-lived token."""
        return SendspinPairingTokenResponse.from_dict({
            "status": SendspinPairingTokenStatus.NOT_READY,
        })


__all__ = ["SendspinProvider"]
