"""Tests for the tag registries.

These guard the two failure modes that produced the 132/133 bug: a number
that disagrees with the FIX 4.4 spec, and a number that exists in one table
but not another.
"""

from fixwire.core.tags import TAG_NAMES, Tags


class TestTagsRegistry:
    """The Tags enum is the single source of truth for field numbers."""

    def test_every_tags_member_is_named(self):
        """Every Tags member has an entry in TAG_NAMES.

        A gap here means a tag is usable in code but invisible to logging
        and debugging, which is how a wrong number hides.
        """
        # Act
        missing = [tag for tag in Tags if tag not in TAG_NAMES]

        # Assert
        assert missing == [], (
            f"Tags members missing from TAG_NAMES: {missing}"
        )

    def test_sequence_tags_match_fix44_spec(self):
        """Sequence-related tag numbers match FIX 4.4.

        These are the numbers that were previously wrong (BeginSeqNo and
        EndSeqNo were 132/133, which are BidPx/OfferPx). Pinned here so a
        future edit cannot silently change them.
        """
        assert Tags.BEGIN_SEQ_NO == 7
        assert Tags.END_SEQ_NO == 16
        assert Tags.MSG_SEQ_NUM == 34
        assert Tags.NEW_SEQ_NO == 36
        assert Tags.POSS_DUP_FLAG == 43
        assert Tags.REF_SEQ_NUM == 45
        assert Tags.TEST_REQ_ID == 112
        assert Tags.GAP_FILL_FLAG == 123
        assert Tags.RESET_SEQ_NUM_FLAG == 141

    def test_header_tags_match_fix44_spec(self):
        """Header tag numbers match FIX 4.4."""
        assert Tags.BEGIN_STRING == 8
        assert Tags.BODY_LENGTH == 9
        assert Tags.CHECKSUM == 10
        assert Tags.MSG_TYPE == 35
        assert Tags.SENDER_COMP_ID == 49
        assert Tags.SENDING_TIME == 52
        assert Tags.TARGET_COMP_ID == 56
