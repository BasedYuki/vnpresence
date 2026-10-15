"""Doing things with a screenshot: show it in Explorer, copy it, share it.

Three small Windows features, each with no package behind it:

* **Show in folder** - Explorer, opened on the folder with the file selected.
* **Copy** - the picture itself onto the clipboard, as a bitmap and as PNG, so
  Ctrl+V in Discord, a browser or Paint pastes the image, not a file path.
* **Share** - the Windows share sheet (Discord, Mail, Nearby Share...), the
  one Explorer's own Share button opens. Windows only offers it to a program
  through WinRT, so it is reached here through ``ctypes``: the share manager
  for our window, a handler that puts the picture in the package when Windows
  asks for it, and the call that opens the sheet. The interface layouts come
  from Microsoft's own metadata; anything that goes wrong raises ShareError,
  and the page falls back to copying the picture instead.

Everything else in VNPresence works without these, so nothing here runs on
import, and nothing here is reached on any other system.
"""

from __future__ import annotations

import ctypes
import hashlib
import io
import logging
import subprocess
import sys
import uuid
from pathlib import Path

log = logging.getLogger(__name__)


class ShareError(RuntimeError):
    pass


# -- show in folder ---------------------------------------------------------
def show_in_folder(path: Path) -> None:
    """Explorer, on the file's folder, with the file selected."""
    path = Path(path)
    try:
        if sys.platform == "win32":
            subprocess.Popen(["explorer", f"/select,{path}"])  # noqa: S603, S607
        else:
            from .gui import open_path

            open_path(path.parent)
    except Exception:
        log.debug("could not show %s", path, exc_info=True)


# -- copy -------------------------------------------------------------------
def image_formats(path: Path) -> tuple[bytes, bytes]:
    """The picture as (DIB, PNG) bytes - the two shapes pasting apps look for.

    A DIB is a .bmp without its 14-byte file header: the header Windows wants
    on the clipboard as CF_DIB. PNG goes alongside it under the registered
    "PNG" format, which browsers and Discord prefer and which keeps the exact
    pixels.
    """
    from PIL import Image

    with Image.open(path) as picture:
        rgb = picture.convert("RGB")
        bmp, png = io.BytesIO(), io.BytesIO()
        rgb.save(bmp, "BMP")
        rgb.save(png, "PNG")
    return bmp.getvalue()[14:], png.getvalue()


CF_DIB = 8
GMEM_MOVEABLE = 0x0002


def copy_image(path: Path) -> None:
    """Put the picture on the clipboard. Raises ShareError if it cannot."""
    if sys.platform != "win32":
        raise ShareError("copying a picture is Windows only")
    dib, png = image_formats(path)
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.SetClipboardData.restype = wintypes.HANDLE
    user32.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
    user32.RegisterClipboardFormatW.restype = wintypes.UINT
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]

    def put(fmt: int, data: bytes) -> None:
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not handle:
            raise ShareError("out of memory for the clipboard")
        pointer = kernel32.GlobalLock(handle)
        ctypes.memmove(pointer, data, len(data))
        kernel32.GlobalUnlock(handle)
        if not user32.SetClipboardData(fmt, handle):
            kernel32.GlobalFree(handle)  # only freed when the clipboard refused it
            raise ShareError("Windows did not take the picture onto the clipboard")

    # Another program can hold the clipboard for a moment; try a few times.
    import time

    for _attempt in range(10):
        if user32.OpenClipboard(None):
            break
        time.sleep(0.05)
    else:
        raise ShareError("the clipboard is busy - another program has it open")
    try:
        user32.EmptyClipboard()
        put(CF_DIB, dib)
        png_format = user32.RegisterClipboardFormatW("PNG")
        if png_format:
            put(png_format, png)
    finally:
        user32.CloseClipboard()


# -- share --------------------------------------------------------------------
def _guid(text: str) -> bytes:
    return uuid.UUID(text).bytes_le


#: How WinRT names a generic interface: a SHA-1 of its signature, under this
#: namespace (the WinRT type system's own rules).
_WINRT_PINTERFACE_NAMESPACE = uuid.UUID("11f47ad5-7b73-42c0-abae-878b1e16adee")


def pinterface_iid(signature: str) -> uuid.UUID:
    """The IID of a parameterized WinRT interface, from its signature."""
    digest = hashlib.sha1(_WINRT_PINTERFACE_NAMESPACE.bytes + signature.encode("utf-8")).digest()
    data = bytearray(digest[:16])
    data[6] = (data[6] & 0x0F) | 0x50  # version 5: name-based, SHA-1
    data[8] = (data[8] & 0x3F) | 0x80  # RFC 4122 variant
    return uuid.UUID(bytes=bytes(data))


IID_IUnknown = "00000000-0000-0000-c000-000000000046"
IID_IAgileObject = "94ea2b94-e9cc-49e0-c0ff-ee64ca8f5b90"
IID_IDataTransferManagerInterop = "3a3dcd6c-3eab-43dc-bcde-45671ce800c8"
IID_IDataTransferManager = "a5caee9b-8708-49d1-8d36-67d25a8da00c"
IID_IDataRequestedEventArgs = "cb8ba807-6ac5-43c9-8ac5-9ba232163182"
IID_IRandomAccessStream = "905a0fe1-bc53-11df-8c49-001e4fc686da"
IID_IRandomAccessStreamReferenceStatics = "857309dc-3fbf-4e7d-986f-ef3b1a07a964"
TYPED_EVENT_HANDLER = "9de1c534-6ae1-11e0-84e1-18a905bcc53f"

#: TypedEventHandler<DataTransferManager, DataRequestedEventArgs>: what our
#: handler has to say it is when Windows asks.
DATA_REQUESTED_HANDLER = pinterface_iid(
    f"pinterface({{{TYPED_EVENT_HANDLER}}};"
    f"rc(Windows.ApplicationModel.DataTransfer.DataTransferManager;{{{IID_IDataTransferManager}}});"
    f"rc(Windows.ApplicationModel.DataTransfer.DataRequestedEventArgs;"
    f"{{{IID_IDataRequestedEventArgs}}}))"
)

# Method slots, counted from the start of each interface's table. IUnknown
# takes 0-2, IInspectable 3-5, so a WinRT interface's own methods start at 6.
_INTEROP_GET_FOR_WINDOW, _INTEROP_SHOW_SHARE_UI = 3, 4
_MANAGER_ADD_DATA_REQUESTED, _MANAGER_REMOVE_DATA_REQUESTED = 6, 7
_ARGS_GET_REQUEST = 6
_REQUEST_GET_DATA, _REQUEST_FAIL = 6, 9
_PACKAGE_GET_PROPERTIES, _PACKAGE_SET_BITMAP = 7, 21
_PROPERTIES_SET_TITLE, _PROPERTIES_SET_DESCRIPTION = 7, 9
_STREAM_STATICS_CREATE_FROM_STREAM = 8

E_NOINTERFACE = 0x80004002 - (1 << 32)
S_OK = 0
RPC_E_CHANGED_MODE = 0x80010106 - (1 << 32)
STGM_READ, STGM_SHARE_DENY_WRITE = 0x0, 0x20


class _Sharer:  # pragma: no cover - Windows only, checked by tools/verify_share.py
    """One per window: the share manager, and the handler Windows calls back."""

    def __init__(self, hwnd: int) -> None:
        from ctypes import wintypes

        self.hwnd = hwnd
        self.path: Path | None = None
        self.title = ""
        #: How the last request went - for tools/verify_share.py to report.
        self.handed_over = 0
        self.last_error = ""
        self.combase = ctypes.WinDLL("combase")
        self.shlwapi = ctypes.WinDLL("shlwapi")
        self.shcore = ctypes.WinDLL("shcore")
        HSTRING = ctypes.c_void_p
        self.combase.RoInitialize.argtypes = [ctypes.c_int]
        self.combase.RoInitialize.restype = ctypes.c_long
        self.combase.WindowsCreateString.argtypes = [
            wintypes.LPCWSTR, ctypes.c_uint32, ctypes.POINTER(HSTRING)]
        self.combase.WindowsCreateString.restype = ctypes.c_long
        self.combase.WindowsDeleteString.argtypes = [HSTRING]
        self.combase.RoGetActivationFactory.argtypes = [
            HSTRING, ctypes.c_char_p, ctypes.POINTER(ctypes.c_void_p)]
        self.combase.RoGetActivationFactory.restype = ctypes.c_long
        self.shlwapi.SHCreateStreamOnFileEx.argtypes = [
            wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.BOOL,
            ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
        self.shlwapi.SHCreateStreamOnFileEx.restype = ctypes.c_long
        self.shcore.CreateRandomAccessStreamOverStream.argtypes = [
            ctypes.c_void_p, ctypes.c_int, ctypes.c_char_p, ctypes.POINTER(ctypes.c_void_p)]
        self.shcore.CreateRandomAccessStreamOverStream.restype = ctypes.c_long

        result = self.combase.RoInitialize(0)  # single-threaded: Tk's thread
        if result < 0 and result != RPC_E_CHANGED_MODE:
            raise ShareError(f"WinRT would not start (0x{result & 0xFFFFFFFF:08x})")

        self.interop = self._factory(
            "Windows.ApplicationModel.DataTransfer.DataTransferManager",
            IID_IDataTransferManagerInterop)
        manager = ctypes.c_void_p()
        self._call(self.interop, _INTEROP_GET_FOR_WINDOW,
                   [wintypes.HWND, ctypes.c_char_p, ctypes.POINTER(ctypes.c_void_p)],
                   wintypes.HWND(hwnd), _guid(IID_IDataTransferManager), ctypes.byref(manager),
                   what="the share manager for this window")
        self.manager = manager.value
        self._make_handler()
        token = ctypes.c_int64()
        self._call(self.manager, _MANAGER_ADD_DATA_REQUESTED,
                   [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int64)],
                   ctypes.addressof(self._handler), ctypes.byref(token),
                   what="the share request handler")
        self.token = token.value

    # -- COM plumbing ---------------------------------------------------------
    @staticmethod
    def _method(pointer: int, slot: int, argtypes: list):
        vtable = ctypes.cast(ctypes.c_void_p(pointer),
                             ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        prototype = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *argtypes)
        return prototype(vtable[slot])

    def _call(self, pointer: int, slot: int, argtypes: list, *args, what: str) -> None:
        result = self._method(pointer, slot, argtypes)(pointer, *args)
        if result < 0:
            raise ShareError(f"Windows refused {what} (0x{result & 0xFFFFFFFF:08x})")

    def _release(self, pointer) -> None:
        if pointer:
            self._method(pointer, 2, [])(pointer)

    def _hstring(self, text: str) -> ctypes.c_void_p:
        handle = ctypes.c_void_p()
        self.combase.WindowsCreateString(text, len(text), ctypes.byref(handle))
        return handle

    def _factory(self, class_name: str, iid: str) -> int:
        name = self._hstring(class_name)
        out = ctypes.c_void_p()
        try:
            result = self.combase.RoGetActivationFactory(name, _guid(iid), ctypes.byref(out))
        finally:
            self.combase.WindowsDeleteString(name)
        if result < 0 or not out.value:
            raise ShareError(f"{class_name} is not available (0x{result & 0xFFFFFFFF:08x})")
        return out.value

    def _make_handler(self) -> None:
        """A COM object of our own, made of ctypes callbacks: the handler."""
        QI = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p,
                                ctypes.POINTER(ctypes.c_void_p))
        REF = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)
        INVOKE = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p,
                                    ctypes.c_void_p)
        accepted = {uuid.UUID(IID_IUnknown).bytes_le, uuid.UUID(IID_IAgileObject).bytes_le,
                    DATA_REQUESTED_HANDLER.bytes_le}

        def query(this, riid, out):
            if ctypes.string_at(riid, 16) in accepted:
                out[0] = this
                return S_OK
            out[0] = None
            return E_NOINTERFACE

        def invoke(_this, _sender, args):
            try:
                self._fill(args)
                self.handed_over += 1
            except Exception as exc:
                self.last_error = repr(exc)
                log.warning("could not hand the picture to the share sheet", exc_info=True)
            return S_OK

        # Lives as long as this object, which lives as long as the window:
        # the reference count is a formality.
        self._callbacks = (QI(query), REF(lambda _this: 1), REF(lambda _this: 1),
                           INVOKE(invoke))
        self._vtable = (ctypes.c_void_p * 4)(
            *[ctypes.cast(cb, ctypes.c_void_p) for cb in self._callbacks])
        self._handler = ctypes.c_void_p(ctypes.addressof(self._vtable))

    # -- the request ------------------------------------------------------------
    def _fill(self, args: int) -> None:
        """Windows asks what is being shared: the title, and the picture."""
        request = package = properties = stream = random_access = statics = reference = None
        try:
            out = ctypes.c_void_p()
            self._call(args, _ARGS_GET_REQUEST, [ctypes.POINTER(ctypes.c_void_p)],
                       ctypes.byref(out), what="the share request")
            request = out.value
            out = ctypes.c_void_p()
            self._call(request, _REQUEST_GET_DATA, [ctypes.POINTER(ctypes.c_void_p)],
                       ctypes.byref(out), what="the share package")
            package = out.value
            out = ctypes.c_void_p()
            self._call(package, _PACKAGE_GET_PROPERTIES, [ctypes.POINTER(ctypes.c_void_p)],
                       ctypes.byref(out), what="the package's properties")
            properties = out.value
            for slot, text in ((_PROPERTIES_SET_TITLE, self.title or "Screenshot"),
                               (_PROPERTIES_SET_DESCRIPTION, self.path.name if self.path else "")):
                handle = self._hstring(text)
                try:
                    self._call(properties, slot, [ctypes.c_void_p], handle,
                               what="the share title")
                finally:
                    self.combase.WindowsDeleteString(handle)

            out = ctypes.c_void_p()
            result = self.shlwapi.SHCreateStreamOnFileEx(
                str(self.path), STGM_READ | STGM_SHARE_DENY_WRITE, 0, False, None,
                ctypes.byref(out))
            if result < 0:
                raise ShareError(f"could not open {self.path}")
            stream = out.value
            out = ctypes.c_void_p()
            result = self.shcore.CreateRandomAccessStreamOverStream(
                stream, 0, _guid(IID_IRandomAccessStream), ctypes.byref(out))
            if result < 0:
                raise ShareError("could not wrap the picture for WinRT")
            random_access = out.value
            statics = self._factory("Windows.Storage.Streams.RandomAccessStreamReference",
                                    IID_IRandomAccessStreamReferenceStatics)
            out = ctypes.c_void_p()
            self._call(statics, _STREAM_STATICS_CREATE_FROM_STREAM,
                       [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)],
                       random_access, ctypes.byref(out), what="a reference to the picture")
            reference = out.value
            self._call(package, _PACKAGE_SET_BITMAP, [ctypes.c_void_p], reference,
                       what="the picture")
        finally:
            for pointer in (reference, statics, random_access, stream, properties, package,
                            request):
                self._release(pointer)

    def show(self, path: Path, title: str) -> None:
        self.path, self.title = Path(path), title
        from ctypes import wintypes

        self._call(self.interop, _INTEROP_SHOW_SHARE_UI, [wintypes.HWND],
                   wintypes.HWND(self.hwnd), what="the share sheet")


_sharers: dict[int, _Sharer] = {}


def share_image(path: Path, hwnd: int, title: str = "Screenshot") -> None:
    """Open the Windows share sheet for this picture, over window ``hwnd``.

    Raises ShareError when Windows will not - older Windows, a policy that
    turns sharing off, or anything in between - so the caller can fall back.
    """
    if sys.platform != "win32":
        raise ShareError("the share sheet is Windows only")
    if not Path(path).is_file():
        raise ShareError(f"{path} is not there any more")
    try:
        sharer = _sharers.get(hwnd)
        if sharer is None:
            sharer = _sharers[hwnd] = _Sharer(hwnd)
        sharer.show(path, title)
    except ShareError:
        raise
    except Exception as exc:  # a ctypes surprise must not take the page down
        raise ShareError(f"could not open the share sheet: {exc}") from exc


def toplevel_hwnd(widget) -> int:
    """The real window handle Windows knows a Tk window by."""
    if sys.platform != "win32":
        return 0
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32")
    user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetAncestor.restype = wintypes.HWND
    GA_ROOT = 2
    inner = widget.winfo_id()
    return int(user32.GetAncestor(inner, GA_ROOT) or inner)
