"""Routing to human review — per field, not per document.

The decision that determines whether a document-processing system is worth deploying.

A forty-field invoice with one uncertain field is not a failed extraction. Rejecting the
whole document sends a human forty fields to re-key when they needed to check one, and
that is the difference between a system that saves money and one that quietly costs
more than the manual process it replaced.

So routing is **per field**, and the queue carries the specific question:

    "Is the total 27,300 or 23,700? The line items sum to 23,700."

not

    "Please review this invoice."

**Critical fields escalate the document; non-critical ones do not.** A misread vendor
address is a nuisance. A misread total is money. Treating them identically is how a
review queue becomes a backlog nobody works.

And validation errors escalate **regardless of confidence** — an invoice whose line items
do not sum to its total is wrong even if every character was read perfectly, and
confidence has nothing to say about it.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from .extract import Classification, ExtractedField
from .schema import DocumentSchema, Issue


@dataclass
class ReviewItem:
    """One specific question for a human, with everything needed to answer it."""

    field: str
    reason: str
    extracted_value: str | None
    candidates: list[str] = field(default_factory=list)
    confidence: float = 0.0
    critical: bool = False
    validation: list[str] = field(default_factory=list)

    def question(self) -> str:
        if self.candidates and len(set(self.candidates)) > 1:
            options = " or ".join(sorted(set(self.candidates)))
            return f"Which is correct for {self.field}: {options}?"
        if self.validation:
            return f"{self.field} = {self.extracted_value!r}. {self.validation[0]}"
        if self.extracted_value is None:
            return f"{self.field} was not found. What is it?"
        return f"Is {self.field} = {self.extracted_value!r} correct?"


@dataclass
class ProcessedDocument:
    document_type: str | None
    classification: Classification
    fields: dict[str, ExtractedField] = field(default_factory=dict)
    issues: list[Issue] = field(default_factory=list)
    review_queue: list[ReviewItem] = field(default_factory=list)
    auto_approved: bool = False
    processed_at: float = field(default_factory=time.time)

    @property
    def values(self) -> dict:
        return {name: f.value for name, f in self.fields.items()}

    @property
    def fields_needing_review(self) -> int:
        return len(self.review_queue)

    @property
    def straight_through(self) -> bool:
        """No human touched it. The metric the business case rests on."""
        return self.auto_approved

    def summary(self) -> dict:
        return {
            "document_type": self.document_type,
            "auto_approved": self.auto_approved,
            "fields_extracted": sum(1 for f in self.fields.values() if f.value),
            "fields_for_review": self.fields_needing_review,
            "errors": sum(1 for i in self.issues if i.severity == "error"),
            "warnings": sum(1 for i in self.issues if i.severity == "warning"),
            "questions": [item.question() for item in self.review_queue],
        }


@dataclass
class ReviewPolicy:
    # Below this, a field is checked by a person.
    min_confidence: float = 0.70
    # Critical fields are held to a higher bar, because the cost of being wrong differs.
    min_confidence_critical: float = 0.85
    # A document with this many uncertain fields is worth re-keying whole.
    max_review_fields: int = 8
    escalate_on_validation_error: bool = True
    escalate_on_disagreement: bool = True


def route(
    classification: Classification,
    fields: dict[str, ExtractedField],
    issues: list[Issue],
    schema: DocumentSchema,
    *,
    policy: ReviewPolicy | None = None,
) -> ProcessedDocument:
    policy = policy or ReviewPolicy()
    document = ProcessedDocument(
        document_type=classification.document_type, classification=classification,
        fields=fields, issues=issues,
    )

    if classification.needs_human:
        # Nothing downstream can be trusted if the document type is wrong, so this
        # escalates whole rather than per field.
        document.review_queue.append(ReviewItem(
            field="document_type", reason=classification.reason,
            extracted_value=None,
            candidates=[c for c in (classification.runner_up,) if c],
            critical=True,
        ))
        return document

    issues_by_field: dict[str, list[Issue]] = {}
    for issue in issues:
        issues_by_field.setdefault(issue.field, []).append(issue)

    for name, extracted in fields.items():
        spec = schema.spec(name)
        critical = bool(spec and spec.critical)
        threshold = (
            policy.min_confidence_critical if critical else policy.min_confidence
        )
        field_issues = issues_by_field.get(name, [])
        errors = [i for i in field_issues if i.severity == "error"]

        reasons: list[str] = []
        if extracted.value is None and spec and spec.required:
            reasons.append("required field not found")
        if extracted.value is not None and extracted.confidence < threshold:
            reasons.append(
                f"confidence {extracted.confidence:.2f} below {threshold:.2f}"
            )
        if policy.escalate_on_disagreement and extracted.disputed:
            reasons.append("extractors disagreed")
        if policy.escalate_on_validation_error and errors:
            # Deliberately independent of confidence: an invoice whose line items do
            # not sum to its total is wrong even if every character was read perfectly.
            reasons.append(errors[0].detail)

        if reasons:
            document.review_queue.append(ReviewItem(
                field=name, reason="; ".join(reasons),
                extracted_value=extracted.value, candidates=extracted.candidates,
                confidence=extracted.confidence, critical=critical,
                validation=[i.detail for i in field_issues],
            ))

    # Document-level errors that belong to no extracted field - cross-field rules
    # naming a field that was never extracted, for instance.
    for issue in issues:
        if issue.severity == "error" and issue.field not in fields:
            document.review_queue.append(ReviewItem(
                field=issue.field, reason=issue.detail, extracted_value=None,
                critical=True, validation=[issue.detail],
            ))

    document.auto_approved = not document.review_queue
    return document


@dataclass
class QueueMetrics:
    """What a manager needs to know about whether this is working."""

    documents: int = 0
    auto_approved: int = 0
    review_items: int = 0
    critical_items: int = 0
    by_field: dict[str, int] = field(default_factory=dict)

    def add(self, document: ProcessedDocument) -> None:
        self.documents += 1
        if document.auto_approved:
            self.auto_approved += 1
        for item in document.review_queue:
            self.review_items += 1
            if item.critical:
                self.critical_items += 1
            self.by_field[item.field] = self.by_field.get(item.field, 0) + 1

    def summary(self) -> dict:
        return {
            "documents": self.documents,
            "straight_through_rate": (
                round(self.auto_approved / self.documents, 4) if self.documents else 0.0
            ),
            "review_items": self.review_items,
            "items_per_document": (
                round(self.review_items / self.documents, 3) if self.documents else 0.0
            ),
            "critical_items": self.critical_items,
            # Which field is costing the most human time. Usually one field accounts
            # for most of the queue, and fixing that one extractor is the whole win.
            "worst_fields": dict(
                sorted(self.by_field.items(), key=lambda kv: -kv[1])[:5]
            ),
        }
