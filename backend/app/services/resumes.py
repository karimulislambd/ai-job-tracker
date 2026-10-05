"""CV upload: validate → extract text from the PDF → store as the new active version."""

from __future__ import annotations

import io
import logging
import uuid

from pypdf import PdfReader
from pypdf.errors import PdfReadError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.errors import (
    NotFoundError,
    PayloadTooLargeError,
    UnsupportedMediaTypeError,
    ValidationFailedError,
)
from app.models import Resume
from app.repositories.resumes import ResumeRepository

logger = logging.getLogger(__name__)

PDF_MAGIC = b"%PDF-"
ALLOWED_CONTENT_TYPES = {"application/pdf", "application/x-pdf"}
MAX_PAGES = 15
MIN_TEXT_CHARS = 50


def extract_pdf_text(data: bytes) -> tuple[str, int]:
    """Return ``(text, page_count)``. Raises ValidationFailedError on unreadable PDFs."""
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise ValidationFailedError("Encrypted PDFs are not supported")
        pages = reader.pages
        if len(pages) > MAX_PAGES:
            raise ValidationFailedError(f"CV must have at most {MAX_PAGES} pages")
        text = "\n".join((page.extract_text() or "") for page in pages)
    except ValidationFailedError:
        raise
    except (PdfReadError, ValueError, KeyError, TypeError, OSError) as exc:
        raise ValidationFailedError("The file could not be read as a PDF") from exc
    # Normalise whitespace while keeping paragraph breaks.
    lines = [" ".join(line.split()) for line in text.splitlines()]
    cleaned = "\n".join(line for line in lines if line).replace("\x00", "")
    return cleaned, len(pages)


class ResumeService:
    def __init__(self, session: AsyncSession, max_bytes: int) -> None:
        self.session = session
        self.max_bytes = max_bytes
        self.repo = ResumeRepository(session)

    def validate_upload(self, data: bytes, filename: str | None, content_type: str | None) -> None:
        if len(data) > self.max_bytes:
            raise PayloadTooLargeError(
                f"File exceeds the {self.max_bytes // (1024 * 1024)} MB limit"
            )
        if len(data) == 0:
            raise ValidationFailedError("The uploaded file is empty")
        # Never trust the declared type or extension alone: check the magic bytes too.
        if (content_type or "").lower() not in ALLOWED_CONTENT_TYPES or not data.startswith(
            PDF_MAGIC
        ):
            raise UnsupportedMediaTypeError("Only PDF files are accepted")
        if filename and not filename.lower().endswith(".pdf"):
            raise UnsupportedMediaTypeError("Only PDF files are accepted")

    async def upload(
        self, user_id: uuid.UUID, data: bytes, filename: str | None, content_type: str | None
    ) -> Resume:
        self.validate_upload(data, filename, content_type)
        text, page_count = await run_in_threadpool(extract_pdf_text, data)
        if len(text) < MIN_TEXT_CHARS:
            raise ValidationFailedError(
                "No selectable text found in the PDF (is it a scanned image?)"
            )
        return await self.create_version(
            user_id,
            text=text,
            filename=(filename or "cv.pdf")[:255],
            page_count=page_count,
            size_bytes=len(data),
        )

    async def create_version(
        self, user_id: uuid.UUID, *, text: str, filename: str, page_count: int, size_bytes: int
    ) -> Resume:
        await self.repo.deactivate_all(user_id)
        resume = await self.repo.add(
            Resume(
                user_id=user_id,
                version=await self.repo.next_version(user_id),
                filename=filename,
                content_text=text,
                page_count=page_count,
                size_bytes=size_bytes,
                is_active=True,
            )
        )
        await self.session.commit()
        return resume

    async def activate(self, user_id: uuid.UUID, resume_id: uuid.UUID) -> Resume:
        resume = await self.repo.get(user_id, resume_id)
        if resume is None:
            raise NotFoundError("Resume not found")
        await self.repo.deactivate_all(user_id)
        await self.session.flush()
        resume.is_active = True
        await self.session.commit()
        await self.session.refresh(resume)
        return resume

    async def get(self, user_id: uuid.UUID, resume_id: uuid.UUID) -> Resume:
        resume = await self.repo.get(user_id, resume_id)
        if resume is None:
            raise NotFoundError("Resume not found")
        return resume

    async def get_active(self, user_id: uuid.UUID) -> Resume:
        resume = await self.repo.get_active(user_id)
        if resume is None:
            raise NotFoundError("No CV uploaded yet")
        return resume

    async def list_for_user(self, user_id: uuid.UUID) -> list[Resume]:
        return await self.repo.list_for_user(user_id)
