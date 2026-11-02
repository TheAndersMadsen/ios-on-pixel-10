# AOSP boot-image unpacker

`unpack_bootimg.py` is an **unmodified** copy from Android Open Source Project
`platform/system/tools/mkbootimg`, commit
`d2bb0af5ba6d3198a3e99529c97eda1be0b5a093`:

[Pinned source](https://android.googlesource.com/platform/system/tools/mkbootimg/+/d2bb0af5ba6d3198a3e99529c97eda1be0b5a093/unpack_bootimg.py).

SHA256: `a9d260978a63bd06a24b6347e7dee8a28ff96639793caea15dff6aa491316308`.
The file retains its AOSP copyright and Apache-2.0 notice. `LICENSE` is the
[canonical Apache-2.0 text](https://www.apache.org/licenses/LICENSE-2.0.txt).
The upstream repository has no `LICENSE` file at this revision; the licence is
stated in the file itself. The separately licensed `bootimg.h` is not vendored.

The original wrapper `tools/android_bootset.py` checks source hash, image extent
and fragment-name bounds before invoking the pinned extractor on a regular local
file. It compares extracted hashes with independently bounded source extents.
It never executes a generated command line. Device images, extracted ramdisks,
DTBs, bootconfig, inventories and provenance receipts stay outside tracked paths.

This package supplies format/extraction behaviour only. It does not verify an
AVB chain, a trusted stock key, slot identity, Android data or bootability.
