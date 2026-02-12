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
    hashed_password = factory.LazyFunction(
        lambda: "$2b$12$LJ3m4ys3Tl0Zj5YK8V6Y5OBZ9Zx8Zv2Xk4Wq3Er1Tp0Sn7Iu6Hm"
    )
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


class ProjectFactory(factory.DictFactory):
    """Factory for editor project dicts."""

    id = factory.LazyFunction(lambda: str(uuid.uuid4()))
    user_id = factory.LazyFunction(lambda: f"user_{uuid.uuid4().hex[:12]}")
    source_media_id = factory.LazyFunction(lambda: str(uuid.uuid4()))
    name = factory.LazyFunction(lambda: f"Project {fake.word().title()}")
    description = factory.LazyFunction(fake.sentence)
    status = "draft"
    settings = factory.LazyFunction(dict)
    created_at = factory.LazyFunction(lambda: datetime.now(UTC))
    updated_at = factory.LazyFunction(lambda: datetime.now(UTC))


class ClipFactory(factory.DictFactory):
    """Factory for clip dicts."""

    id = factory.LazyFunction(lambda: str(uuid.uuid4()))
    project_id = factory.LazyFunction(lambda: str(uuid.uuid4()))
    start_time = factory.LazyFunction(lambda: fake.pyfloat(min_value=0.0, max_value=100.0))
    end_time = factory.LazyFunction(lambda: fake.pyfloat(min_value=101.0, max_value=300.0))
    title = factory.LazyFunction(lambda: f"Clip: {fake.sentence(nb_words=3)}")
    notes = factory.LazyFunction(fake.sentence)
    order = factory.Sequence(lambda n: n)
    is_ai_suggested = False
    viral_score = None
    viral_reasons = None
    transcript_snippet = factory.LazyFunction(lambda: fake.paragraph(nb_sentences=2))
