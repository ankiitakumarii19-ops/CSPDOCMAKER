"""
CSP DocMaker — a person's profile picture (No. 171)

Optional. One row per signed-in person, keyed by their email (lower case),
so a picture follows the person into every workspace they belong to, like
their name. No row = the screens show their initials, as before.

Kept in the database like every other file the app holds (D5); always a
square JPEG of at most 256 x 256, made from the upload.
"""

from datetime import datetime

from sqlalchemy import DateTime, Integer, LargeBinary, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class UserPhoto(Base):
    __tablename__ = "user_photos"

    email: Mapped[str] = mapped_column(String(255), primary_key=True)
    image: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    content_type: Mapped[str] = mapped_column(String(50), nullable=False,
                                              default="image/jpeg")
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False,
                                          comment="SHA-256; also the picture's version")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False)

    def __repr__(self) -> str:
        return f"<UserPhoto {self.email} {self.file_size}B>"
