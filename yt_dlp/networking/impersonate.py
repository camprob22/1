from .exceptions import UnsupportedRequest
from .utils import std_headers


class ImpersonateHandlerMixin:
    """
    Mixin class for request handlers that support browser impersonation.

    This mixin class provides a method for checking the validity of the impersonate extension,
    which can be used in _check_extensions.

    The following may be defined:
     `SUPPORTED_IMPERSONATE_TARGETS`: a tuple of supported targets to impersonate,
        in curl-impersonate target name format. Any Request with an impersonate
        target not in this list will raise an UnsupportedRequest.
        Set to None to disable this check.
    """
    _SUPPORTED_IMPERSONATE_TARGETS: tuple = ()

    def _check_impersonate_extension(self, extensions):
        if self._SUPPORTED_IMPERSONATE_TARGETS is None:
            return
        target = extensions.get('impersonate')
        if not isinstance(target, str):
            raise UnsupportedRequest(f'Impersonate extension must be of type str, got {type(target)}')
        if target not in self._SUPPORTED_IMPERSONATE_TARGETS:
            raise UnsupportedRequest(f'Unsupported impersonate target: {target}')

    def _get_impersonate_headers(self, request):
        headers = self._merge_headers(request.headers)
        impersonate = request.extensions.get('impersonate')
        if impersonate:
            # remove all headers present in std_headers
            headers.pop('User-Agent', None)
            for header in std_headers:
                if header in headers and std_headers[header] == headers[header]:
                    headers.pop(header, None)
        return headers
