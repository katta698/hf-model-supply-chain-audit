"""Classify a Hub licence tag by what a commercial review would decide.

The Hub's `license` tag is a flat string, which hides the only distinction that
matters in practice: can this ship in a product, and what does that oblige us to
do? Four buckets:

  permissive      ship it, attribution at most
  conditional     commercial use allowed, but with obligations (naming,
                  acceptable-use policies, copyleft, share-alike)
  non_commercial  cannot ship in a commercial product, full stop
  unclearable     the tag carries no decidable information; a human must read
                  the actual terms in the repo

`unclearable` is deliberately separate from the rest. It is not a risk rating,
it is an admission that automation cannot answer the question -- which is itself
the finding, because it means the licence gate has to be manual.
"""

PERMISSIVE = {
    "apache-2.0",
    "mit",
    "bsd",
    "bsd-2-clause",
    "bsd-3-clause",
    "bsl-1.0",
    "cc0-1.0",
    "cc-by-4.0",
    "cc-by-3.0",
    "cc-by-2.0",
    "isc",
    "unlicense",
    "artistic-2.0",
    "zlib",
    "postgresql",
    "wtfpl",
    "ecl-2.0",
}

# Commercial use is permitted but carries obligations: copyleft/share-alike
# reciprocity, acceptable-use policies, or naming and notice requirements.
CONDITIONAL = {
    "mpl-2.0",
    "lgpl-2.1",
    "lgpl-3.0",
    "gpl-2.0",
    "gpl-3.0",
    "agpl-3.0",
    "epl-1.0",
    "epl-2.0",
    "osl-3.0",
    "cc-by-sa-3.0",
    "cc-by-sa-4.0",
    "apple-ascl",
    "apple-amlr",
    "deepfloyd-if-license",
    "fair-noncommercial-research-license",
}

# Prefix matches, for licence families the Hub tags per-release.
CONDITIONAL_PREFIXES = (
    "llama",        # llama2, llama3, llama3.1 ... naming + acceptable-use terms
    "gemma",        # Google acceptable-use policy
    "openrail",     # RAIL use restrictions
    "bigscience-openrail",
    "bigcode-openrail",
    "creativeml-openrail",
    "qwen",         # some Qwen releases carry bespoke terms
)

NON_COMMERCIAL_PREFIXES = ("cc-by-nc",)

NON_COMMERCIAL = {
    "cc-by-nd-4.0",
}

# Tags that exist but decide nothing.
UNCLEARABLE = {None, "", "other", "unknown"}

PERMISSIVE_BUCKET = "permissive"
CONDITIONAL_BUCKET = "conditional"
NON_COMMERCIAL_BUCKET = "non_commercial"
UNCLEARABLE_BUCKET = "unclearable"

BUCKETS = (
    PERMISSIVE_BUCKET,
    CONDITIONAL_BUCKET,
    NON_COMMERCIAL_BUCKET,
    UNCLEARABLE_BUCKET,
)


# Most-restrictive-first, for resolving multi-licence declarations. Ordered by
# how much it blocks an automated gate: cannot ship > needs a human > ship with
# obligations > ship.
SEVERITY = (
    NON_COMMERCIAL_BUCKET,
    UNCLEARABLE_BUCKET,
    CONDITIONAL_BUCKET,
    PERMISSIVE_BUCKET,
)


def classify(license_tag):
    """Return one of BUCKETS for a Hub licence tag.

    A card may declare several licences (`license: [apache-2.0, other]`). That
    is ambiguous: it can mean "take your pick" or "different parts, different
    terms", and the tag does not say which. We resolve to the most restrictive
    bucket present, because assuming the generous reading is how an automated
    gate ends up shipping something it shouldn't.
    """
    if isinstance(license_tag, (list, tuple, set)):
        if not license_tag:
            return UNCLEARABLE_BUCKET
        buckets = {classify(tag) for tag in license_tag}
        return next(b for b in SEVERITY if b in buckets)

    if not isinstance(license_tag, str):
        return UNCLEARABLE_BUCKET

    if license_tag in UNCLEARABLE:
        return UNCLEARABLE_BUCKET

    tag = license_tag.strip().lower()

    # Non-commercial is checked first: cc-by-nc-sa also matches share-alike,
    # and the stricter answer is the correct one.
    if tag in NON_COMMERCIAL or tag.startswith(NON_COMMERCIAL_PREFIXES):
        return NON_COMMERCIAL_BUCKET
    if tag in PERMISSIVE:
        return PERMISSIVE_BUCKET
    if tag in CONDITIONAL or tag.startswith(CONDITIONAL_PREFIXES):
        return CONDITIONAL_BUCKET

    # An unrecognised tag is unclearable, not permissive. Failing open here
    # would be the whole bug this module exists to avoid.
    return UNCLEARABLE_BUCKET


def ship_without_review(license_tag):
    """True only when no human needs to look at the licence."""
    return classify(license_tag) == PERMISSIVE_BUCKET


def export_rules():
    """The policy as plain data, so other runtimes can apply the same rules.

    The browser-based Space reimplements classify() in JavaScript. Rather than
    maintain two copies of the licence lists -- which would drift, and would
    mean the public tool grading models differently from the published dataset
    -- both read from this one export.
    """
    return {
        "permissive": sorted(PERMISSIVE),
        "conditional": sorted(CONDITIONAL),
        "conditional_prefixes": sorted(CONDITIONAL_PREFIXES),
        "non_commercial": sorted(NON_COMMERCIAL),
        "non_commercial_prefixes": sorted(NON_COMMERCIAL_PREFIXES),
        "unclearable": sorted(t for t in UNCLEARABLE if t),
        "severity": list(SEVERITY),
    }
