"""Stage 3 bid intake: safe zip extraction, PDF discovery, bid grouping.

Real bids arrive as zip archives with inconsistent folder layouts. This module
extracts all archives for ONE bid into a dedicated directory and discovers PDF
files anywhere in the extracted tree. It never uses folder names or filenames to
assign meaning (Req 1.3) -- it only collects PDF paths.

Security: ``safe_extract_member`` rejects any entry whose resolved path escapes
the bid directory (zip-slip / path traversal), handling absolute paths and
``../`` traversal (Req 1.6). All writes are confined to the bid directory.
"""
from __future__ import annotations

import zipfile
from pathlib import Path
from zipfile import ZipFile, ZipInfo

from tender_app.evaluation.models import BidIntakeResult


def safe_extract_member(zf: ZipFile, member: ZipInfo, dest: Path) -> Path | None:
    """Resolve ``member``'s target path under ``dest`` and extract it there.

    Returns the written file path for legitimate file entries, or ``None`` when
    the entry is rejected (zip-slip / traversal) or is a directory entry.

    - Rejects (returns ``None``, writes nothing) any entry whose resolved path
      falls outside ``dest`` -- covers absolute paths and ``../`` traversal.
    - Creates parent directories for legitimate entries.
    - Skips directory entries safely (returns ``None``, creates the dir).
    """
    dest_root = dest.resolve()

    # Normalize the member name: strip any leading drive/root so an absolute
    # entry name like "/etc/passwd" or "C:\\evil" cannot anchor outside dest.
    # We still verify containment after resolving to catch "../" traversal.
    raw_name = member.filename
    # zip entries always use forward slashes; also guard backslashes.
    normalized = raw_name.replace("\\", "/")

    target = (dest_root / normalized).resolve()

    # Containment check: target must be dest_root itself or inside it.
    if target != dest_root and dest_root not in target.parents:
        # Entry escapes the bid directory -> reject, write nothing.
        return None

    # Directory entry: create it, but do not treat it as a written file.
    if member.is_dir() or raw_name.endswith("/"):
        target.mkdir(parents=True, exist_ok=True)
        return None

    # Legitimate file entry: ensure parent dirs exist, then write.
    target.parent.mkdir(parents=True, exist_ok=True)
    with zf.open(member) as src, open(target, "wb") as out:
        out.write(src.read())
    return target


def _discover_pdfs(root: Path) -> list[Path]:
    """Recursively discover all PDF files under ``root`` by content location.

    Matches ``.pdf`` case-insensitively anywhere in the tree. Folder names and
    filenames are not used to assign meaning (Req 1.3); they are only collected.
    """
    pdfs = [p for p in root.rglob("*") if p.is_file() and p.suffix.lower() == ".pdf"]
    return sorted(pdfs)


def extract_bid(archives: list[Path], bid_id: str, run_dir: Path) -> BidIntakeResult:
    """Extract all zip archives for ONE bid into ``run_dir/bid_id/``.

    Treats multiple archives as one bid (Req 1.2). After extraction, recursively
    discovers all PDF files in the extracted tree (Req 1.1/1.3). Confines all
    writes to the bid directory (Req 1.6). If no readable PDF is found, sets
    ``evaluable = False`` (Req 1.4).

    Non-zip or unreadable archives are skipped gracefully (e.g. ``.rar`` members
    nested inside, or a corrupt zip) so a single bad input does not abort intake.
    """
    bid_dir = (run_dir / bid_id)
    bid_dir.mkdir(parents=True, exist_ok=True)
    bid_dir = bid_dir.resolve()

    archive_count = 0
    for archive in archives:
        archive = Path(archive)
        if not archive.is_file() or not zipfile.is_zipfile(archive):
            # Non-zip / unreadable archive -> skip gracefully.
            continue
        try:
            with ZipFile(archive) as zf:
                archive_count += 1
                for member in zf.infolist():
                    # safe_extract_member confines every write to bid_dir and
                    # rejects escaping entries (zip-slip).
                    safe_extract_member(zf, member, bid_dir)
        except zipfile.BadZipFile:
            # Corrupt archive -> skip gracefully.
            continue

    pdf_paths = _discover_pdfs(bid_dir)
    evaluable = len(pdf_paths) > 0

    return BidIntakeResult(
        bid_id=bid_id,
        bid_dir=str(bid_dir),
        pdf_paths=[str(p) for p in pdf_paths],
        evaluable=evaluable,
        archive_count=archive_count,
    )
