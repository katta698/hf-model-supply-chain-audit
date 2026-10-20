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


def classify(license_tag):
    """Return one of BUCKETS for a Hub licence tag."""
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
