"""
flavor_connectives.py  --  shared connective-phrase bank for the wordbank
generators (flavor_hf.py, flavor_entity.py, flavor_bestiary.py)

Each of those files builds a blurb as one lead-in sentence followed by
extra sentences that fold in more word-bank picks. Every extra sentence
needs a connective phrase to introduce it. All three files used to keep
their own small (8-10 item) list of these, which is why the same handful
of phrases (like "Reports add {j}.") turned up constantly across every
kind of page. This is one shared, much larger pool instead, built out
along the same lines a real chronicle would vary its transitions: by
time, by source, by cause, by disagreement, or by confirmation.

Every template takes one {j} slot, filled with a comma-joined phrase from
the relevant word bank.
"""

CONNECTORS = [
    # time
    "Years later, {j}.",
    "Years earlier, {j}.",
    "In the years that followed, {j}.",
    "In the years before this, {j}.",
    "Over the course of their life, {j}.",
    "Around this time, {j}.",
    "Not long afterward, {j}.",
    "Not long before this, {j}.",
    "Eventually, {j}.",
    "In time, {j}.",
    "As the years passed, {j}.",
    "As time went on, {j}.",
    "Meanwhile, {j}.",
    "By this point, {j}.",
    "Much later, {j}.",
    "Much earlier, {j}.",

    # elsewhere / additional
    "Elsewhere in the record, {j}.",
    "Elsewhere in the chronicles, {j}.",
    "Elsewhere in the annals, {j}.",
    "In another account, {j}.",
    "Additionally, {j}.",
    "Further accounts describe {j}.",
    "Notably, {j}.",
    "Likewise, {j}.",
    "Similarly, {j}.",
    "Beyond this, {j}.",
    "Alongside this, {j}.",
    "In particular, {j}.",
    "In turn, {j}.",

    # cause and consequence
    "This followed {j}.",
    "This came in response to {j}.",
    "This appears to have been prompted by {j}.",
    "This was accompanied by {j}.",
    "This coincided with {j}.",
    "The cause appears to have been {j}.",
    "This was likely connected to {j}.",
    "This added further weight to {j}.",

    # disagreement and uncertainty
    "Not all accounts agree, some point instead to {j}.",
    "The surviving accounts differ, with some describing {j}.",
    "Other accounts instead claim {j}.",
    "Later histories offer another interpretation, pointing to {j}.",
    "The precise circumstances remain unclear, though some cite {j}.",
    "There is some disagreement here, with several accounts citing {j}.",
    "Some accounts instead point to {j}.",

    # confirmation and certainty
    "The records are clear on {j}.",
    "Multiple accounts confirm {j}.",
    "The chronicles firmly establish {j}.",
    "There is little doubt surrounding {j}.",
    "Several sources agree on {j}.",

    # retrospective significance
    "This would later prove central to {j}.",
    "This would become closely associated with {j}.",
    "Its significance grew with time, tied to {j}.",
    "This would eventually come to define {j}.",

    # plain report (kept short and few, so they can't dominate the pool)
    "Accounts also mention {j}.",
    "Others recall {j}.",
    "The record also notes {j}.",
]
