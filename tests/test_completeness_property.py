"""Property-based tests for ``tender_app.evaluation.completeness``."""
from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from tender_app.evaluation import completeness
from tender_app.evaluation.models import RequiredDocumentType, SubDocument


# A pool of stable document-type keys to draw from.
_key = st.text(
    alphabet=st.characters(
        min_codepoint=97, max_codepoint=122, whitelist_categories=("Ll",)
    ),
    min_size=1,
    max_size=6,
)


@st.composite
def _types_and_subdocs(draw):
    """Generate unique required-document types plus sub-documents whose
    ``classified_as`` is drawn from those type keys or 'Unclassified'."""
    keys = draw(st.lists(_key, min_size=0, max_size=6, unique=True))
    types = [RequiredDocumentType(key=k, label=k.upper()) for k in keys]

    # classified_as is drawn from the type keys or "Unclassified".
    class_choices = keys + ["Unclassified"] if keys else ["Unclassified"]

    n_subs = draw(st.integers(min_value=0, max_value=10))
    sub_docs = []
    for i in range(n_subs):
        classified = draw(st.sampled_from(class_choices))
        readable = draw(st.booleans())
        sub_docs.append(
            SubDocument(
                filename=f"doc{i}.pdf",
                page_start=1,
                page_end=1,
                classified_as=classified,
                readable=readable,
            )
        )
    return types, sub_docs


# Feature: bid-evaluation, Property 2: For any set of classified sub-documents and required-document types, completeness.check_completeness marks the bid complete iff every required-document type has at least one present-and-readable sub-document; any missing or present-but-unreadable type yields complete = False.
@settings(max_examples=100)
@given(_types_and_subdocs())
def test_completeness_biconditional(data):
    # Validates Requirements 4.1, 4.2, 4.3, 4.4, 4.5.
    types, sub_docs = data
    result = completeness.check_completeness(sub_docs, types)

    # Independently compute the expected outcome from first principles.
    expected_complete = all(
        any(s.classified_as == t.key and s.readable for s in sub_docs)
        for t in types
    )
    assert result.complete is expected_complete

    # A type is "missing" iff NO sub-doc at all is classified as that key.
    expected_missing = {
        t.key for t in types
        if not any(s.classified_as == t.key for s in sub_docs)
    }
    # A type is "unreadable" iff it has matches but none readable.
    expected_unreadable = {
        t.key for t in types
        if any(s.classified_as == t.key for s in sub_docs)
        and not any(s.classified_as == t.key and s.readable for s in sub_docs)
    }

    assert set(result.missing) == expected_missing
    assert set(result.unreadable) == expected_unreadable
