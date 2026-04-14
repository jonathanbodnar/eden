import enum


class ActorType(str, enum.Enum):
    DEITY = "deity"
    RULER = "ruler"
    MYTHIC_FIGURE = "mythic_figure"
    HISTORICAL_PERSON = "historical_person"
    COLLECTIVE = "collective"
    UNKNOWN = "unknown"


class EventType(str, enum.Enum):
    CREATION = "creation"
    FLOOD = "flood"
    WAR = "war"
    MIGRATION = "migration"
    FOUNDING = "founding"
    RITUAL = "ritual"
    ASTRONOMICAL = "astronomical"
    DEATH = "death"
    SUCCESSION = "succession"
    TRADE = "trade"
    CONSTRUCTION = "construction"
    UNKNOWN = "unknown"


class PlaceType(str, enum.Enum):
    CITY = "city"
    TEMPLE = "temple"
    RIVER = "river"
    MOUNTAIN = "mountain"
    REGION = "region"
    UNDERWORLD = "underworld"
    CELESTIAL = "celestial"
    SACRED_SITE = "sacred_site"
    UNKNOWN = "unknown"


class ThreadType(str, enum.Enum):
    KINGSHIP = "kingship"
    DIVINE_CONFLICT = "divine_conflict"
    CREATION_CYCLE = "creation_cycle"
    HERO_JOURNEY = "hero_journey"
    DESCENT = "descent"
    FLOOD_CYCLE = "flood_cycle"
    CULTURAL_TRANSMISSION = "cultural_transmission"
    UNKNOWN = "unknown"


class HintType(str, enum.Enum):
    ACTOR = "actor"
    EVENT = "event"
    PLACE = "place"


class CanonicalType(str, enum.Enum):
    EPOCH = "epoch"
    CHAPTER = "chapter"
    ACTOR = "actor"
    EVENT = "event"
    PLACE = "place"
    STORY_THREAD = "story_thread"
    BRANCH = "branch"


class SupportType(str, enum.Enum):
    PRIMARY_EVIDENCE = "primary_evidence"
    SECONDARY_CONTEXT = "secondary_context"
    CORROBORATING = "corroborating"
    CONTRADICTING = "contradicting"


class ArchiveObjectType(str, enum.Enum):
    SOURCE_RECORD = "source_record"
    SOURCE_VERSION = "source_version"
    SEGMENT = "segment"
    CONTEXTUAL_STATEMENT = "contextual_statement"


class WorldJobType(str, enum.Enum):
    EXTRACT_HINTS = "extract_hints"
    SYNTH_CANON = "synth_canon"
    BUILD_CHAPTERS = "build_chapters"
    BUILD_NARRATION = "build_narration"
    BUILD_WORLD_PACKETS = "build_world_packets"
    UPDATE_CANON = "update_canon"
    GENERATE_SCRIPT = "generate_script"
    GENERATE_VISUALS = "generate_visuals"
    GENERATE_AUDIO = "generate_audio"
    ASSEMBLE_VIDEO = "assemble_video"


class WorldJobStatus(str, enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PAUSED = "paused"
    CANCELED = "canceled"


class ChangeType(str, enum.Enum):
    NEW_SEGMENT = "new_segment"
    UPDATED_SEGMENT = "updated_segment"
    NEW_STATEMENT = "new_statement"
    UPDATED_STATEMENT = "updated_statement"
    NEW_SOURCE = "new_source"


class UpdateTargetStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ChatRole(str, enum.Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class AnswerMode(str, enum.Enum):
    SOURCE = "source"
    CONTEXT = "context"
    SYNTHESIS = "synthesis"
    UNSUPPORTED = "unsupported"


class VideoType(str, enum.Enum):
    CHAPTER_VIDEO = "chapter_video"
    EVENT_VIDEO = "event_video"
    CHARACTER_VIDEO = "character_video"


class VideoAssetType(str, enum.Enum):
    KEYFRAME = "keyframe"
    MOTION_CLIP = "motion_clip"
    NARRATION_AUDIO = "narration_audio"
    AMBIENCE = "ambience"


class VideoAssetStatus(str, enum.Enum):
    PENDING = "pending"
    GENERATING = "generating"
    COMPLETED = "completed"
    FAILED = "failed"
