"""Expected ZIP decoder failures, shared by backup and resource-pack readers."""

import zipfile
import zlib

ZIP_READ_ERRORS: tuple[type[Exception], ...] = (zipfile.BadZipFile, zlib.error, EOFError, RuntimeError)

# These codecs are optional in Python builds; Zstandard ZIPs require Python 3.14.
try:
    from lzma import LZMAError
except ImportError:
    pass
else:
    ZIP_READ_ERRORS += (LZMAError,)

try:
    from compression.zstd import ZstdError
except ImportError:
    pass
else:
    ZIP_READ_ERRORS += (ZstdError,)
