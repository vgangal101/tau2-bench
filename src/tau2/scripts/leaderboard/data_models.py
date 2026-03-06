"""Pydantic data models for tau2-bench leaderboard submissions.

These models match the JSON schema used in the web leaderboard submissions.
"""

from datetime import date
from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class BaseModelStrict(BaseModel):
    """Base model with strict configuration."""

    model_config = ConfigDict(extra="forbid")


class ContactInfo(BaseModelStrict):
    """Contact information for the submission."""

    email: Optional[str] = Field(
        None, description="Contact email for questions about this submission"
    )
    name: Optional[str] = Field(None, description="Name of the submitter")
    github: Optional[str] = Field(None, description="GitHub username (optional)")


class DomainResults(BaseModelStrict):
    """Results for a specific domain."""

    pass_1: Optional[float] = Field(
        None, ge=0, le=100, description="Pass^1 success rate percentage"
    )
    pass_2: Optional[float] = Field(
        None, ge=0, le=100, description="Pass^2 success rate percentage"
    )
    pass_3: Optional[float] = Field(
        None, ge=0, le=100, description="Pass^3 success rate percentage"
    )
    pass_4: Optional[float] = Field(
        None, ge=0, le=100, description="Pass^4 success rate percentage"
    )
    cost: Optional[float] = Field(
        None,
        ge=0,
        description="Average cost in USD to run one trajectory in this domain",
    )

    def get_pass_k(self, k: int) -> Optional[float]:
        """Get pass^k score for a given k."""
        if k < 1 or k > 4:
            raise ValueError(f"k must be between 1 and 4, got {k}")
        return getattr(self, f"pass_{k}")


class Results(BaseModelStrict):
    """Performance results for each domain."""

    retail: Optional[DomainResults] = None
    airline: Optional[DomainResults] = None
    telecom: Optional[DomainResults] = None

    def get_domain(self, domain: str) -> Optional[DomainResults]:
        """Get results for a specific domain."""
        domain_lower = domain.lower()
        if domain_lower == "retail":
            return self.retail
        elif domain_lower == "airline":
            return self.airline
        elif domain_lower == "telecom":
            return self.telecom
        else:
            raise ValueError(
                f"Invalid domain: {domain}. Must be retail, airline, or telecom."
            )

    @property
    def available_domains(self) -> list[str]:
        """Get list of domains that have results."""
        domains = []
        if self.retail is not None:
            domains.append("retail")
        if self.airline is not None:
            domains.append("airline")
        if self.telecom is not None:
            domains.append("telecom")
        return domains


class ReferenceType(str, Enum):
    """Type of reference."""

    PAPER = "paper"
    BLOG = "blog"  # Alternative spelling
    BLOG_POST = "blog_post"
    DOCUMENTATION = "documentation"
    MODEL_CARD = "model_card"
    GITHUB = "github"
    HUGGINGFACE = "huggingface"
    TECHNICAL_REPORT = "technical_report"
    OTHER = "other"


class ReferenceInfo(BaseModelStrict):
    """Reference link information."""

    title: str = Field(..., description="Title or description of the reference")
    url: str = Field(..., description="URL to the reference")
    type: Optional[ReferenceType] = Field(None, description="Type of reference")


class VerificationInfo(BaseModelStrict):
    """Verification details for result authenticity."""

    modified_prompts: Optional[bool] = Field(
        None,
        description="Whether any modifications were made to user simulator or agent prompts",
    )
    omitted_questions: Optional[bool] = Field(
        None,
        description="Whether any questions/tasks were omitted from the evaluation",
    )
    details: Optional[str] = Field(
        None, description="Additional verification details or explanations"
    )


class Methodology(BaseModelStrict):
    """Information about how the evaluation was conducted."""

    evaluation_date: Optional[date] = Field(
        None, description="Date when evaluation was conducted"
    )
    tau2_bench_version: Optional[str] = Field(
        None, description="Version of tau2-bench used for evaluation"
    )
    user_simulator: Optional[str] = Field(
        None,
        description="Model used for user simulation during evaluation",
    )
    notes: Optional[str] = Field(
        None, description="Additional notes about the evaluation methodology"
    )
    verification: Optional[VerificationInfo] = Field(
        None, description="Verification details for result authenticity"
    )


class Submission(BaseModel):
    """Tau2-Bench Leaderboard Submission model.

    This model matches the JSON schema used in the web leaderboard.
    """

    model_config = ConfigDict(
        extra="allow"
    )  # Allow extra fields for forward compatibility

    # Required fields
    model_name: str = Field(..., description="Name of the model being evaluated")
    model_organization: str = Field(
        ..., description="Organization that developed the model"
    )
    submitting_organization: str = Field(
        ...,
        description="Organization that ran the evaluation and submitted the results",
    )
    submission_date: date = Field(
        ..., description="Date of submission in YYYY-MM-DD format"
    )
    contact_info: ContactInfo = Field(..., description="Contact information")
    results: Results = Field(..., description="Performance results for each domain")

    # Optional fields
    is_new: bool = Field(
        False,
        description="Whether this model should be highlighted as new on the leaderboard",
    )
    trajectories_available: bool = Field(
        False, description="Whether trajectory files are available for this submission"
    )
    references: list[ReferenceInfo] = Field(
        default_factory=list,
        description="Links to papers, blog posts, documentation, or other resources",
    )
    notes: Optional[str] = Field(
        None, description="Additional notes about the submission"
    )
    methodology: Optional[Methodology] = Field(
        None, description="Information about how the evaluation was conducted"
    )

    # Internal field (set after loading)
    _submission_id: Optional[str] = None

    @property
    def submission_id(self) -> Optional[str]:
        """Get the submission ID (folder name)."""
        return self._submission_id

    def set_submission_id(self, submission_id: str) -> None:
        """Set the submission ID."""
        self._submission_id = submission_id

    @classmethod
    def load(cls, path: Path | str) -> "Submission":
        """Load a submission from a JSON file."""
        path = Path(path)
        with open(path, "r") as f:
            submission = cls.model_validate_json(f.read())
        # Set submission ID from parent folder name
        submission.set_submission_id(path.parent.name)
        return submission

    def get_pass_1_average(self) -> Optional[float]:
        """Get the average pass^1 score across all available domains."""
        scores = []
        for domain in self.results.available_domains:
            domain_results = self.results.get_domain(domain)
            if domain_results and domain_results.pass_1 is not None:
                scores.append(domain_results.pass_1)
        if not scores:
            return None
        return sum(scores) / len(scores)


class LeaderboardManifest(BaseModelStrict):
    """Manifest file listing all submissions."""

    submissions: list[str] = Field(
        default_factory=list, description="List of submission folder names"
    )
    last_updated: Optional[str] = Field(
        None, description="ISO timestamp of last update"
    )


class LeaderboardEntry(BaseModel):
    """A leaderboard entry with computed ranking information."""

    submission: Submission
    rank: Optional[int] = None
    score: Optional[float] = None  # The score used for ranking

    model_config = ConfigDict(arbitrary_types_allowed=True)


# Constants
SUBMISSION_FILE_NAME = "submission.json"
TRAJECTORY_FILES_DIR_NAME = "trajectories"
MANIFEST_FILE_NAME = "manifest.json"
DOMAINS = ["retail", "airline", "telecom"]
METRICS = ["pass_1", "pass_2", "pass_3", "pass_4", "cost"]
