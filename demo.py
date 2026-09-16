"""Three documents in. Two go straight through, one raises a single question.

    python demo.py

The point is not how many fields were extracted. It is how few a human is
asked to look at, and whether the right ones were picked. No network, no OCR.
"""

import sys

sys.path.insert(0, "src")

from docintel.api import SAMPLE_DOCUMENTS
from docintel.pipeline import process

DOCS = [
    ("clean_invoice", "a well-formed invoice"),
    ("broken_total_invoice", "subtotal + tax does not equal total"),
    ("cnic", "a Pakistani identity card"),
]

print("INPUT")
for key, note in DOCS:
    first = SAMPLE_DOCUMENTS[key].strip().split("\n")[0]
    print(f"   {key:22} {first:34} ({note})")
print()

print("OUTPUT")
for key, _note in DOCS:
    doc = process(SAMPLE_DOCUMENTS[key])
    route = "STRAIGHT THROUGH" if doc.straight_through else "NEEDS A HUMAN"
    print(f"   {key:22} type={doc.document_type or '?':10} fields={len(doc.fields):<3} {route}")
    for item in doc.review_queue:
        print(f"      ask a human   {item.field}: {item.reason}")
    for issue in doc.issues:
        if not any(issue.detail == r.reason for r in doc.review_queue):
            print(f"      issue         [{issue.severity}] {issue.field}: {issue.detail}")
print()
print("   The broken invoice has every field present and legible. No OCR")
print("   confidence score would have caught it: the numbers are clear, they")
print("   just do not add up. That check is arithmetic, not vision.")
