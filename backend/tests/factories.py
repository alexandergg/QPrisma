"""
Test Data Factories for QPrisma.

Uses factory-boy with Faker for generating realistic test data.
Returns dicts matching the shapes expected by services and routes.
"""

import uuid
from datetime import UTC, datetime

import factory
from faker import Faker

fake = Faker()


class UserFactory(factory.DictFactory):
    """Factory for user data dicts."""

    id = factory.LazyFunction(lambda: f"user_{uuid.uuid4().hex[:12]}")
    email = factory.LazyFunction(fake.email)
    full_name = factory.LazyFunction(fake.name)
    entra_oid = factory.LazyFunction(lambda: str(uuid.uuid4()))
    is_active = True
    is_superuser = False
    created_at = factory.LazyFunction(lambda: datetime.now(UTC))
    updated_at = factory.LazyFunction(lambda: datetime.now(UTC))


class MediaFactory(factory.DictFactory):
    """Factory for media metadata dicts."""

    id = factory.LazyFunction(lambda: str(uuid.uuid4()))
    user_id = factory.LazyFunction(lambda: f"user_{uuid.uuid4().hex[:12]}")
    blob_name = factory.LazyFunction(lambda: f"{uuid.uuid4()}.mp4")
    original_filename = factory.LazyFunction(lambda: f"{fake.word()}_video.mp4")
    media_type = "video"
    file_size = factory.LazyFunction(lambda: fake.random_int(min=1024, max=1073741824))
    content_type = "video/mp4"
    processed = False
    processing_status = "uploaded"
    processing_message = None
    processing_progress = 0.0
    job_id = None
    video_metadata = factory.LazyFunction(
        lambda: {
            "duration": fake.pyfloat(min_value=10.0, max_value=3600.0),
            "fps": 30.0,
            "width": 1920,
            "height": 1080,
        }
    )


class JobFactory(factory.DictFactory):
    """Factory for job data dicts."""

    id = factory.LazyFunction(lambda: str(uuid.uuid4()))
    media_id = factory.LazyFunction(lambda: str(uuid.uuid4()))
    user_id = factory.LazyFunction(lambda: f"user_{uuid.uuid4().hex[:12]}")
    status = "pending"
    progress = 0
    stage = "queued"
    message = None
    error = None
    created_at = factory.LazyFunction(lambda: datetime.now(UTC))
