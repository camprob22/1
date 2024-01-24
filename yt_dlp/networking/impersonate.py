from __future__ import annotations

from abc import ABC
from dataclasses import dataclass
from typing import Any, Optional

from .common import RequestHandler, register_preference
from .exceptions import UnsupportedRequest
from ..compat.types import NoneType
from ..utils import classproperty


@dataclass(order=True, frozen=True)
class ImpersonateTarget:
    """
    A target for browser impersonation.

    Parameters:
    @param client: the client to impersonate
    @param version: the client version to impersonate
    @param os: the client OS to impersonate
    @param os_vers: the client OS version to impersonate

    Note: None is used to indicate to match any.
    """
    client: Optional[str] = None
    version: Optional[str] = None
    os: Optional[str] = None
    os_vers: Optional[str] = None

    def __contains__(self, target: ImpersonateTarget):
        if not isinstance(target, ImpersonateTarget):
            return False
        return (
            (self.client is None or target.client is None or self.client == target.client)
            and (self.version is None or target.version is None or self.version == target.version)
            and (self.os is None or target.os is None or self.os == target.os)
            and (self.os_vers is None or target.os_vers is None or self.os_vers == target.os_vers)
        )

    def __str__(self):
        return ':'.join(part or '' for part in (
            self.client, self.version, self.os, self.os_vers)).rstrip(':')

    @classmethod
    def from_str(cls, target: str):
        return cls(*(v.strip() or None for v in target.split(':')))


class ImpersonateRequestHandler(RequestHandler, ABC):
    """
    Base class for request handlers that support browser impersonation.

    This provides a method for checking the validity of the impersonate extension,
    which can be used in _check_extensions.

    Impersonate targets consist of a client, version, os and os_vers.
    See the ImpersonateTarget class for more details.

    The following may be defined:
     - `_SUPPORTED_IMPERSONATE_TARGET_MAP`: a dict mapping supported targets to custom object.
                Any Request with an impersonate target not in this list will raise an UnsupportedRequest.
                Set to None to disable this check.
                Note: Entries are in order of preference

    Parameters:
    @param impersonate: the default impersonate target to use for requests.
                        Set to None to disable impersonation.
    """
    _SUPPORTED_IMPERSONATE_TARGET_MAP: dict[ImpersonateTarget, Any] = {}

    _IMPERSONATE_HEADERS_BLACKLIST = [
        # Headers to remove from provided headers when impersonating.
        # In the networking framework, the provided headers are intended
        # to give a consistent user agent across request handlers.
        # However, it is intended that the impersonation implementation will add the required headers to mimic a client.
        # So we need to remove provided headers that may interfere with this behaviour.
        # TODO(future): Add a method of excluding headers from this blacklist, such as User-Agent in certain cases.
        # TODO(future): "Accept" should be included here, however it is currently required for some sites.
        'User-Agent',
        'Accept-Language',
        'Sec-Fetch-Mode',
        'Sec-Fetch-Site',
        'Sec-Fetch-User',
        'Sec-Fetch-Dest',
        'Upgrade-Insecure-Requests',
        'Sec-Ch-Ua',
        'Sec-Ch-Ua-Mobile',
        'Sec-Ch-Ua-Platform',
    ]

    def __init__(self, *, impersonate: ImpersonateTarget = None, **kwargs):
        super().__init__(**kwargs)
        self.impersonate = impersonate

    def _check_impersonate_target(self, target: ImpersonateTarget):
        assert isinstance(target, (ImpersonateTarget, NoneType))
        if target is None or not self.supported_targets:
            return
        if not self.is_supported_target(target):
            raise UnsupportedRequest(f'Unsupported impersonate target: {target}')

    def _check_extensions(self, extensions):
        super()._check_extensions(extensions)
        if 'impersonate' in extensions:
            self._check_impersonate_target(extensions.get('impersonate'))

    def _validate(self, request):
        super()._validate(request)
        self._check_impersonate_target(self.impersonate)

    def _resolve_target(self, target: ImpersonateTarget | None):
        """Resolve a target to a supported target."""
        if target is None:
            return
        for supported_target in self.supported_targets:
            if target in supported_target:
                if self.verbose:
                    self._logger.stdout(
                        f'{self.RH_NAME}: resolved impersonate target {target} to {supported_target}')
                return supported_target

    @classproperty
    def supported_targets(self) -> tuple[ImpersonateTarget, ...]:
        return tuple(self._SUPPORTED_IMPERSONATE_TARGET_MAP.keys())

    def is_supported_target(self, target: ImpersonateTarget):
        assert isinstance(target, ImpersonateTarget)
        return self._resolve_target(target) is not None

    def _get_request_target(self, request):
        """Get the requested target for the request"""
        return request.extensions.get('impersonate') or self.impersonate

    def _get_mapped_request_target(self, request):
        """Get the resolved mapped target for the request target"""
        resolved_target = self._resolve_target(self._get_request_target(request))
        return self._SUPPORTED_IMPERSONATE_TARGET_MAP.get(
            resolved_target, None)

    def _get_impersonate_headers(self, request):
        headers = self._merge_headers(request.headers)
        if self._get_request_target(request) is not None:
            for header in self._IMPERSONATE_HEADERS_BLACKLIST:
                headers.pop(header, None)
        return headers


@register_preference(ImpersonateRequestHandler)
def impersonate_preference(rh, request):
    if request.extensions.get('impersonate') is not None or rh.impersonate is not None:
        return 1000
    return 0